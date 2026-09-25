# Phase 1B: BCI engine and arbiter

**Agent:** opus3 · **Runs:** Phase 1, in parallel with 1A, 1C–1E

## Goal
Everything between the headset and the velocity command: open the board
(auto-detecting the dongle), run the existing decoder, and turn its output
into a safe `vx`/`vy` command with arming, dwell and auto-disarm. Exposed to
the server as `BciEngine`. Also the SSVEP board simulator, so the whole loop
runs without a headset.

## Stack
Python 3.10, numpy/scipy, brainflow via eegnb, pyserial (port auto-detect),
the existing `control/ssvep_bci.Decoder`.

## Read first
- [../protocol.md](../protocol.md): `EngineSettings`, `BciEngine`,
  `SimSSVEPBoard`, the `state` engine fields, the safety model
- `control/ssvep_bci.py`: `Decoder`, `harmonic_clashes`,
  `PREFERRED_CHANNELS`, and how `main()` opens the board and picks channels
- `control/ssvep_trca.py`: `FilterBankTRCA`, `load_calibration` (optional `--model` path)
- [../README.md](../README.md#rules-for-every-agent): git and environment rules

## You own
`hub/bci/__init__.py`, `hub/bci/config.py`, `hub/bci/board.py`,
`hub/bci/arbiter.py`, `hub/bci/engine.py`, `hub/sim/sim_board.py`,
`hub/tests/test_arbiter.py`, `hub/tests/test_engine.py`,
`hub/tests/test_sim_board.py`

## Build

1. **Import the decoder, don't copy or edit it.** Insert
   `<repo>/control` on `sys.path` and `from ssvep_bci import Decoder, ...`.
   Importing it does not load psychopy; keep it that way. `control/` is
   read-only.

2. **`config.py`**: `EngineSettings` exactly as in protocol.md.

3. **`board.py`**
   - `find_openbci_port() -> str`: scan `serial.tools.list_ports`. The
     OpenBCI dongle is an FTDI chip (VID `0x0403`, usually PID `0x6015`).
     Exactly one match → return it. None → raise with the list of ports seen
     and "pass --port COMx". Several → raise listing them. This PC also has
     **Bluetooth serial ports (COM3, COM4, "Standard Serial over Bluetooth
     link")**: never pick those. The dongle isn't plugged in right now, so
     test the logic with faked port lists.
   - `open_board(settings)` → an object/tuple with `board`, `fs`,
     `ch_rows`, `ch_names`, `device`, `port`:
     - `cyton`: `EEG(device="cyton", serial_port=port)` from
       `eegnb.devices.eeg`. **Never pass `serial_port=None`**: eegnb then
       asks for the port with `input()` and hangs the hub. `EEG()` already
       calls `prepare_session`; you call `board.start_stream()`.
     - `synthetic`: `EEG(device="synthetic")`.
     - `sim`: `hub.sim.sim_board.SimSSVEPBoard(freqs)` (step 6).
     - Channel picking as in `ssvep_bci.main()`: prefer O1, O2, P7, P8;
       fall back to the first four.

4. **`arbiter.py`**: pure logic, no threads or I/O, fully unit-tested.
   - Inputs: each new decode's `winner` (id or None); `armed`; override
     `(direction, expires_at)`; `eeg_ok`; `dwell`, `speed`.
   - Priority: not armed → none/zero. Override active → override direction,
     `source: "override"`. EEG not ok → zero. Otherwise BCI with dwell.
   - **Dwell:** a direction activates once it has been the winner for
     `dwell` consecutive decodes. When the winner becomes None or anything
     else, the active direction drops **immediately** (look away = stop), and
     a new direction must dwell again.
   - Direction → velocity per the table in protocol.md (`vy` positive = left).
   - Exposes the `dwell` progress for `state`.

5. **`engine.py`**: `BciEngine` exactly as in protocol.md.
   - `start()`: open the board, start the stream, settle ~3 s, start the
     decoder and an engine loop thread (every 50 ms).
   - **New-decode detection:** `Decoder` has no sequence counter. Subclass
     it here and bump a counter when a decode really completed (its `_step`
     returns early while the buffer fills). Feed each decode to the arbiter
     exactly once.
   - **Reconfiguration:** freqs, window or margin change → start a new
     `Decoder`, stop the old one, reset dwell. For `sim`, also call
     `board.set_freqs(...)`.
   - **Validation in `handle(set_config)`:** freqs 5–40 Hz and distinct;
     window 0.5–6 s; margin 0–1; dwell 1–10; speed 0–1. Reject bad values
     without changing anything. Put harmonic clashes (`harmonic_clashes`)
     and freqs above 40 Hz (120 Hz / 3) in `warnings`.
   - **`handle()` sources:** `arm` from phone or dashboard. `override` and
     `sim_gaze` only from the dashboard. `sim_gaze` only when device is `sim`.
     Arming is refused while EEG is not ok. A phone is **not** required to
     arm, so dashboard-only testing works.
   - **Auto-disarm** (protocol.md safety model): phone count 1→0 →
     `phone_lost`; newest EEG sample unchanged > 1.5 s → `eeg_stall`; robot
     disconnect while armed → `robot_lost`.
   - **Quality (optional, cheap):** every 1 s, per decoding channel, the
     std in µV over the last second, and `railed` if |x| > 180000 µV (the
     Cyton rails at ±187500).
   - **`--model` path:** same as `ssvep_bci.main()`: fit `FilterBankTRCA`
     from `load_calibration`, downgrade `trca` to `trca_cca`.
   - Every public method except `start`/`stop` is thread-safe and
     non-blocking: one lock, no I/O.

6. **`hub/sim/sim_board.py`: `SimSSVEPBoard`**, exactly the interface in
   protocol.md.
   - **Real-time:** samples are generated from the monotonic clock at `fs`
     (250). `get_current_board_data(n)` returns the newest `n` samples as
     `(n_rows, n)`, EEG in µV on rows 1–8, row 0 a sample counter. Keep
     ~10 s of history. Generate from the absolute sample index so phase is
     continuous across calls.
   - **Signal:**
     - background: 1/f-ish noise (~10 µV rms) + a 10 Hz alpha component +
       small 50 Hz line noise;
     - while gazing at target *i*: a sinusoid at `freqs[i]` plus 2nd and 3rd
       harmonics, strongest on O1/O2, weaker on P7/P8, faint elsewhere
       (Cyton order: Fp1 Fp2 C3 C4 P7 P8 O1 O2), amplitude scaled by `snr`.
   - Gaze changes take effect at the moment they're made. The decoder's
     window then holds a realistic mix, so the latency is realistic.
   - Thread-safe: the decoder thread reads while the engine calls `set_gaze`/`set_freqs`.
   - Tune the default `snr` so it's realistic but reliable (see tests).

7. **Tests**
   - `test_arbiter.py`: dwell activation; immediate release on None and on
     a different winner; override precedence and 500 ms expiry; disarmed →
     zero; direction→velocity signs.
   - `test_engine.py`: `synthetic` start/stop and `status()` shape; `handle`
     return values and validation; auto-disarm on phone loss; `sim` device:
     armed + `sim_gaze: "left"` → `command()` shows `left`, `vy > 0` within
     ~5 s, and gaze None → zero soon after.
   - `test_sim_board.py`: feed `SimSSVEPBoard` to the real `Decoder`
     (window 3 s, margin 0.06). After 3 s of gaze at each target, the winner
     equals that target in >= 90% of decodes. With gaze None the winner is
     None in >= 80% of decodes. Frequency changes are respected. Keep it
     under ~60 s.

## Acceptance
- [ ] `BciEngine` matches protocol.md exactly, so 1A can swap out `StubEngine` without changes
- [ ] `--device cyton` without a dongle fails fast with a clear message (no `input()` prompt)
- [ ] Sim gaze drives the right direction with the right velocity signs; look-away stops
- [ ] All safety rules in protocol.md covered by tests
- [ ] `SimSSVEPBoard` meets the decoding accuracy targets with its default `snr`
- [ ] `control/.venv/Scripts/python.exe -m pytest hub/tests/test_arbiter.py hub/tests/test_engine.py hub/tests/test_sim_board.py` passes
- [ ] Handoff notes filled in, committed, @main tagged

## Handoff notes
_(fill in when done)_

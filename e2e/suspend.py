import ctypes, sys, time
k = ctypes.windll.kernel32; pid = int(sys.argv[1]); secs = float(sys.argv[2])
assert k.DebugActiveProcess(pid); k.DebugSetProcessKillOnExit(False)
print("frozen", flush=True); time.sleep(secs); k.DebugActiveProcessStop(pid); print("resumed", flush=True)

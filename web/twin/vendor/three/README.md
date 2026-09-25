three.js r186 (`three@0.186.1`), vendored so the pages work offline (no CDN).

- `three.module.js` + `three.core.js`: from `build/`
- `addons/controls/OrbitControls.js`: from `examples/jsm/controls/`
- `LICENSE`: MIT

Pages map the bare specifier with an import map:
`{"imports": {"three": "./vendor/three/three.module.js", "three/addons/": "./vendor/three/addons/"}}`

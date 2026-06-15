# Video Studio Test Scenarios

## 1. UI Build
- `npm run build` completes.
- Main app loads from the Vite output.

## 2. Worker Static
- Python worker modules compile.
- Focused pytest suite for touched render/source/quality modules passes.

## 3. Render Proof
- Manifest renders with no placeholder fallback unless explicitly expected.
- Output decodes with FFmpeg.
- QA summary records source readiness, caption layout, and publish-readiness gates.

## 4. Provider Boundary
- Missing provider credentials fail closed.
- Browser-control proof paths use signed-in Chrome only when explicitly needed.
- Generated or downloaded source artifacts record provenance.


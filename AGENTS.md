# PMSM Performance Tool Development Notes

- Keep numerical calculation code independent from PySide6 UI modules.
- Use SI units and phase peak current/voltage inside `calculation/`.
- Add or update regression tests for every change to equations or constraints.
- Never populate GUI plots with values that did not come from the calculation layer.
- Keep JSON backward compatibility within major format version 1.

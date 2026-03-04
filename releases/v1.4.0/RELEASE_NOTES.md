# Galactic AI v1.4.0 Release Notes

## v1.4.0 — The Hive Mind Update (2026-03-03)

### Added
- **Hive Mind Subagents**: Developed deeply integrated hierarchical agent structures. Subagents are now visualized cleanly in the Control Deck UI (`Thinking` tab), providing seamless parallel processing without interrupting the mainframe ReAct loop.
- **Dynamic Screenshot Buffer Rendering**: Fixed `screenshot` functionalities skipping valid OS image viewer pathways. The buffer is now returned safely to the local LLM and accurately parsed without relying on disk IO bottlenecks or missing object references.
- **UI Web Deck Overhaul**: Overhauled the frontend with high-aesthetic modern gradients, dynamic glassmorphism aesthetics, modern animations/micro-interactions, and premium styling for standard buttons.

### Fixed
- **Playwright DOM Search Submission**: Explicitly hardened browser tool `enter: true` parameters seamlessly clicking and submitting JS-rendered search bars, massively boosting the reliability of the `chrome_type` browser extensions on complex sites.
- **Legacy EXE Deprecation**: Completely eliminated all traces of `build_exe.ps1` and `GalacticAI.spec` to stream-line execution time natively via Python without unneeded packaging, bloat, or anti-virus restrictions.
- **Version String Sanitization**: Resolved numerous hardcoded versions tracking the deprecated `v1.3.0` strings across `web_deck.py` and `remote_access.py`. 

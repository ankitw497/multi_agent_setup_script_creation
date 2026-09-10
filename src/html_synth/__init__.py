"""html_synth — plan §12 (V1B).

Dual-audience HTML synthesis: video_script.html (render source) + page.html (publishable).

component_library.py: the channel component library (plan §7), deterministic rendering.
synthesizer.py: H, the Sonnet pass that writes screen prose and picks components per beat.
assembler.py: deterministic assembly of both files from one shared render path.
"""

# Dzomdu — Signal → Substance

Original 15-second motion graphics film. Delivery: `../04-dzomdu-signal-to-substance-15s.mp4`.

1920 × 1080, 30 fps, 450 video frames, H.264, stereo AAC at 48 kHz. Both streams and the container are exactly 15.000 seconds. Final loudness measured at −16.05 LUFS; true peak −2.21 dBTP. Complete video/audio decode passed.

## Editable projects

- `source/dzomdu-signal-to-substance.ecproj`: EffectCraft composition with individually editable text, vector geometry, gradients, parenting, motion blur, and eased keyframes.
- `source/dzomdu-final.filmcraft`: FilmCraft finishing sequence with picture and sound.
- `source/dzomdu-score.scraft`: SoundCraft session with separate rhythm, bass, glass, atmosphere, and transition tracks, reverb, compression, limiting, and master fade automation. Its audio is saved in the adjacent `source/Audio Files` folder.
- `source/signal-mark.vectorcraft`: VectorCraft signal mark, also exported as SVG and PNG in `assets`.

## Sequence

0.00–2.36: Every voice / expanding wave signal.
2.36–5.02: Speaker memory / three named voice tiles.
5.02–9.18: Conversation becomes decisions and actions / floating transcript and minutes cards.
9.18–11.74: Local by design / rotating wire lattice and orbital nodes.
11.74–15.00: Signal mark and staggered Dzomdu wordmark / brand close.

## Sound and reproducibility

The original 128 BPM electronic score is synthesized by `source/compose_audio.py`, then mixed in SoundCraft. No sampled music or borrowed reference footage appears in the finished piece. Example meeting dialogue is fictional.

The ArtCraft command sequences are retained in `source/animation-commands.json` and `source/finishing-commands.json`; the native EffectCraft project is the authoritative finished animation, including final adjustments and easing. EffectCraft renders the picture, SoundCraft bounces the score, and FilmCraft produces the combined master. Final packaging preserves the video bitstream, trims AAC padding to precisely 15 seconds, and places the MP4 index at the front for prompt playback.

The supplied Ambi reference informed the atmospheric background and floating-interface direction. All artwork, animation, typography choreography, and music in this film were created for Dzomdu.

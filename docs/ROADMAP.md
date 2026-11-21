# TinyWorlds roadmap

## v0.1: a useful local developer preview

Ship the smallest path we have real evidence for: describe a procedural Godot
game, generate it with Codex, play the Web export, and request an edit while
keeping the generated source available locally.

The release work is tracked in [release scope](releases/v0.1-developer-preview.md)
and [readiness](open-source-readiness.md). Freeze the source and finish setup,
notices, acceptance and public-repository preparation before adding features.

## After the preview

- Improve installation from feedback by people using a fresh machine.
- Check real gameplay and mobile controls beyond startup/render smoke tests.
- Validate Claude and Bevy separately before promoting them as supported paths.
- Evaluate optional skills against a no-skill baseline before claiming benefit.
- Use optional agent traces to investigate failures and define reproducible evaluations.

Voice and the separate agent-play prototype are experimental.
Their code is not a commitment to production support or a generated-game
multiplayer feature. Historical plans and experiments are retained in the
private development archive rather than presented as current shipped promises.

# Drawing and photo context

On Create or the game editing composer, choose **Sketch or photo**. Draw directly,
take a photo of paper using the phone camera, or upload an existing image. Review
the thumbnail and explain the requested change before sending. The same control
and JSON context contract work for Godot and Bevy creation and streaming edits.
Bevy's non-streaming edit endpoint also accepts the reference.

PNG, JPEG and WebP are accepted up to 10 MB and 16 megapixels. The server decodes
the image, honors camera orientation, downsizes to 2048 pixels, strips metadata,
and saves a normalized PNG under the game's owner-private `_user_uploads` folder.
The agent sees its path and guidance to inspect visual design context. Raw photo
bytes are not logged as events and must not be copied into public game assets.
This is design context, not an exact tracing/vectorization or animation guarantee.

The shared `reference_image` JSON object contains `filename`, `content_type`, and
`data_base64`. The browser sends it once on the initial POST; reconnects follow
the existing run using GET and never automatically submit another paid job.
Godot's existing multipart edit API remains compatible. Unsupported camera image
formats need conversion to JPEG/PNG before upload. Original references are private
even for public games; derived artwork follows the game's normal sharing policy.

## Draw a level

Inside the drawing dialog choose **A level**, then draw or photograph a map.
The normal create/edit request carries a `purpose: "level"` reference. The agent
receives explicit guidance to build paths/platforms, obstacles and collisions,
a safe spawn and a reachable goal. This uses the game's normal generation job;
it is not a deterministic tracing engine. Ambiguous marks can need clarification
in the edit prompt. Preview and test the generated level before sharing it.

## Bring a character into a game

Choose **A character** and draw one character on plain white paper. Before the
job starts, a bounded Pillow operation removes edge-connected near-white paper,
preserves enclosed white details, and crops a separate transparent PNG. Blank
white drawings fail with a useful message. The original stays private; the agent
is told to integrate only the derived sprite as a playable actor, with collision
bounds and simple movement/idle animation. Animation here can use transforms;
this does not automatically synthesize a multi-frame animation sheet. Shadowy
photos and colored paper can need a clearer retake.

## Circle a change

In the game page choose **Pictures**, open **Mark a change**, and drag a circle
around the area to edit. Sending the marked screenshot puts it in the normal
composer with a starter instruction you can change before submitting. The
request carries `purpose: "annotation"`; the agent is told to preserve unmarked
behavior and never copy the markup into the artwork. Owner-only screenshot lists
and annotation work for both engine APIs. A game needs a saved screenshot first.

Reference purpose is retained in IndexedDB draft storage and in private upload
metadata so reloading or reusing a request preserves the selected workflow.
Both engines accept `idea` (default), `level`, `character`, and `annotation`.

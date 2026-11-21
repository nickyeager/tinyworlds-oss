# Assets lessons

Asset planning + generation (xAI Grok images/video, Tripo3D GLBs, rembg).

- For prompts that name only geometric primitives ("red square", "blue circle", "orange rectangle platform"), do NOT spend xAI/Tripo3D budget. Render with `ColorRect`, `draw_circle`, `Polygon2D`, or `_draw()` directly.
  (why: every successful involved game in this project's history — Square Jumper, TopDownDodger, Neon Pong — uses primitives only. xAI image cost is 2-7¢ per asset; spending it on shapes the engine renders for free is pure waste.)
- Bind named colors from the prompt as `Color(...)` constants at the top of the script that uses them, not as hex literals scattered through `_draw()`.
  (why: 2026-05-04 TopDownDodger declared `circle_color = Color(0.20, 0.55, 1.0)` and `draw_circle(player_pos, PLAYER_RADIUS, circle_color)` — easy for the user to retheme, no magic numbers in the gameplay code.)

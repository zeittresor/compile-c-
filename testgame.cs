// github.com/zeittresor
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Windows.Forms;

namespace BreakoutWinForms
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new BreakoutForm());
        }
    }

    internal sealed class BreakoutForm : Form
    {
        private enum GameState { Title, Playing, LevelCleared, GameOver, Paused }

        private readonly Timer _timer;
        private readonly Stopwatch _clock = new Stopwatch();
        private long _lastTicks;

        private GameState _state = GameState.Title;

        // Paths / assets
        private readonly string _dataDir;
        private readonly string _highScorePath;
        private Image _imgPaddle, _imgBall, _imgTitle;
        private readonly List<Image> _imgBlocks = new List<Image>(); // multiple styles

        // Game objects
        private RectangleF _paddle;
        private float _paddleBaseWidth = 180f;
        private float _paddleHeight = 22f;

        private Vec2 _ballPos;
        private Vec2 _ballVel;
        private Vec2 _ballPrevPos;
        private float _ballRadius = 10f;
        private float _ballBaseSpeed = 520f; // px/s

        private readonly List<Block> _blocks = new List<Block>();
        private readonly List<Particle> _particles = new List<Particle>();
        private readonly List<PowerUp> _powerUps = new List<PowerUp>();

        private int _level = 0;
        private int _score = 0;
        private int _highScore = 0;
        private int _lives = 3;

        // Effects
        private float _widenTimer = 0f;
        private float _slowTimer = 0f;

        // Input
        private int _mouseX;

        // RNG (deterministic-ish per level)
        private readonly Random _rng = new Random(1337);

        public BreakoutForm()
        {
            Text = "Testgame";
            ClientSize = new Size(960, 540);
            MinimumSize = new Size(720, 420);
            StartPosition = FormStartPosition.CenterScreen;
            KeyPreview = true;

            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer, true);
            DoubleBuffered = true;

            _dataDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "data");
            _highScorePath = Path.Combine(_dataDir, "highscore.txt");

            // Loop timer
            _timer = new Timer { Interval = 16 }; // ~60fps
            _timer.Tick += (_, __) => TickFrame();

            // Input hooks
            MouseMove += (_, e) => _mouseX = e.X;
            MouseDown += (_, e) =>
            {
                if (e.Button == MouseButtons.Left)
                    HandleStartOrLaunch();
            };
            KeyDown += (_, e) =>
            {
                if (e.KeyCode == Keys.Escape) Close();
                if (e.KeyCode == Keys.Space) HandleStartOrLaunch();
                if (e.KeyCode == Keys.P) TogglePause();
                if (e.KeyCode == Keys.Enter && _state == GameState.GameOver) StartNewRun();
            };

            Load += (_, __) =>
            {
                EnsureDataAssets();
                LoadAssets();
                LoadHighScore();

                ResetLayout();
                _state = GameState.Title;

                _clock.Start();
                _lastTicks = _clock.ElapsedTicks;
                _timer.Start();
            };

            FormClosing += (_, __) =>
            {
                SaveHighScoreIfNeeded();
                SafeDisposeImages();
            };
        }

        private void TogglePause()
        {
            if (_state == GameState.Playing) _state = GameState.Paused;
            else if (_state == GameState.Paused) _state = GameState.Playing;
        }

        private void HandleStartOrLaunch()
        {
            if (_state == GameState.Title)
            {
                StartNewRun();
                return;
            }

            if (_state == GameState.GameOver)
            {
                StartNewRun();
                return;
            }

            // Launch: if ball is "stuck" on paddle (vel ~ 0), launch it
            if (_state == GameState.Playing && _ballVel.Length() < 0.01f)
            {
                LaunchBall();
            }
        }

        private void StartNewRun()
        {
            _score = 0;
            _lives = 3;
            _level = 0;
            _particles.Clear();
            _powerUps.Clear();

            ResetLayout();
            BuildLevel(_level);

            _state = GameState.Playing;
            StickBallToPaddle();
        }

        private void ResetLayout()
        {
            float px = ClientSize.Width * 0.5f - _paddleBaseWidth * 0.5f;
            float py = ClientSize.Height - 60f;

            _paddle = new RectangleF(px, py, _paddleBaseWidth, _paddleHeight);
            _mouseX = (int)(px + _paddle.Width / 2f);

            _ballRadius = Math.Max(8f, Math.Min(12f, ClientSize.Width / 80f));
            StickBallToPaddle();
        }

        private void StickBallToPaddle()
        {
            _ballVel = new Vec2(0, 0);
            _ballPos = new Vec2(_paddle.X + _paddle.Width / 2f, _paddle.Y - _ballRadius - 1f);
            _ballPrevPos = _ballPos;
        }

        private void LaunchBall()
        {
            // launch with slight horizontal bias based on where the mouse is
            float center = _paddle.X + _paddle.Width / 2f;
            float hit = Clamp((_mouseX - center) / (_paddle.Width / 2f), -1f, 1f);

            float speed = CurrentBallSpeed();
            // angle: -70..+70 degrees
            float angle = hit * (70f * (float)Math.PI / 180f);

            // up is negative y
            _ballVel = new Vec2((float)Math.Sin(angle) * speed, (float)-Math.Cos(angle) * speed);
            if (_ballVel.Y > -120f) _ballVel.Y = -120f; // ensure it goes up
        }

        private float CurrentBallSpeed()
        {
            float s = _ballBaseSpeed;
            if (_slowTimer > 0f) s *= 0.72f;
            return s;
        }

        private void TickFrame()
        {
            // Handle resize dynamics lightly
            if (_paddle.Y > ClientSize.Height - 30f)
                ResetLayout();

            long now = _clock.ElapsedTicks;
            long deltaTicks = now - _lastTicks;
            _lastTicks = now;

            double seconds = (double)deltaTicks / Stopwatch.Frequency;
            float dt = (float)Math.Min(0.033, seconds); // clamp big frame jumps

            if (_state == GameState.Playing)
                UpdateGame(dt);
            else if (_state == GameState.LevelCleared)
                UpdateLevelCleared(dt);
            else if (_state == GameState.Paused)
                UpdateParticlesAndPowerups(dt, allowPowerups: false); // keep particles alive, freeze gameplay

            Invalidate();
        }

        private float _levelClearedTimer = 0f;

        private void UpdateLevelCleared(float dt)
        {
            _levelClearedTimer -= dt;
            UpdateParticlesAndPowerups(dt, allowPowerups: false);

            if (_levelClearedTimer <= 0f)
            {
                _level++;
                BuildLevel(_level);
                StickBallToPaddle();
                _state = GameState.Playing;
            }
        }

        private void UpdateGame(float dt)
        {
            // Effects
            if (_widenTimer > 0f) _widenTimer -= dt;
            if (_slowTimer > 0f) _slowTimer -= dt;

            // Paddle follow mouse
            float targetX = _mouseX - _paddle.Width / 2f;
            float maxX = ClientSize.Width - _paddle.Width;
            _paddle.X = Clamp(targetX, 0f, Math.Max(0f, maxX));
            _paddle.Y = ClientSize.Height - 60f;

            // Apply widen effect
            float desiredWidth = _paddleBaseWidth * (_widenTimer > 0f ? 1.35f : 1f);
            desiredWidth = Clamp(desiredWidth, 120f, Math.Max(160f, ClientSize.Width * 0.45f));
            float center = _paddle.X + _paddle.Width / 2f;
            _paddle.Width = desiredWidth;
            _paddle.Height = _paddleHeight;
            _paddle.X = Clamp(center - _paddle.Width / 2f, 0f, ClientSize.Width - _paddle.Width);

            // Ball
            _ballPrevPos = _ballPos;

            // If not launched, keep stuck
            if (_ballVel.Length() < 0.01f)
            {
                _ballPos = new Vec2(_paddle.X + _paddle.Width / 2f, _paddle.Y - _ballRadius - 1f);
                UpdateParticlesAndPowerups(dt, allowPowerups: true);
                return;
            }

            _ballPos += _ballVel * dt;

            // Walls
            if (_ballPos.X - _ballRadius < 0f)
            {
                _ballPos.X = _ballRadius;
                _ballVel.X = Math.Abs(_ballVel.X);
                SpawnWallSparks(_ballPos, new Vec2(1, 0));
            }
            if (_ballPos.X + _ballRadius > ClientSize.Width)
            {
                _ballPos.X = ClientSize.Width - _ballRadius;
                _ballVel.X = -Math.Abs(_ballVel.X);
                SpawnWallSparks(_ballPos, new Vec2(-1, 0));
            }
            if (_ballPos.Y - _ballRadius < 0f)
            {
                _ballPos.Y = _ballRadius;
                _ballVel.Y = Math.Abs(_ballVel.Y);
                SpawnWallSparks(_ballPos, new Vec2(0, 1));
            }

            // Lose life
            if (_ballPos.Y - _ballRadius > ClientSize.Height + 20f)
            {
                _lives--;
                if (_lives <= 0)
                {
                    GameOver();
                }
                else
                {
                    StickBallToPaddle();
                }
                UpdateParticlesAndPowerups(dt, allowPowerups: true);
                return;
            }

            // Paddle collision (only if coming down)
            if (_ballVel.Y > 0f)
            {
                var ballRect = BallBounds();
                if (ballRect.IntersectsWith(_paddle))
                {
                    // Move ball above paddle
                    _ballPos.Y = _paddle.Y - _ballRadius - 1f;

                    float paddleCenter = _paddle.X + _paddle.Width / 2f;
                    float hit = Clamp((_ballPos.X - paddleCenter) / (_paddle.Width / 2f), -1f, 1f);

                    float speed = CurrentBallSpeed() * 1.02f; // tiny speed-up on paddle hit
                    float angle = hit * (70f * (float)Math.PI / 180f);

                    _ballVel = new Vec2((float)Math.Sin(angle) * speed, (float)-Math.Cos(angle) * speed);

                    SpawnHitSparks(new Vec2(_ballPos.X, _paddle.Y), Color.FromArgb(220, 255, 255, 255), 22);
                }
            }

            // Blocks collision
            bool hitBlock = false;
            RectangleF bRect = BallBounds();

            for (int i = _blocks.Count - 1; i >= 0; i--)
            {
                if (!_blocks[i].Alive) continue;

                if (!bRect.IntersectsWith(_blocks[i].Rect))
                    continue;

                // resolve penetration with overlap method
                Vec2 normal;
                float push;
                ResolveRectOverlap(_blocks[i].Rect, out normal, out push);

                _ballPos += normal * push;

                // reflect
                if (Math.Abs(normal.X) > 0.5f) _ballVel.X *= -1f;
                if (Math.Abs(normal.Y) > 0.5f) _ballVel.Y *= -1f;

                // Damage block
                var blk = _blocks[i];
                blk.HitsLeft--;
                if (blk.HitsLeft <= 0)
                {
                    blk.Alive = false;
                    _score += 10 + (blk.Style * 2);
                    SpawnBlockBurst(blk.Rect, blk.ColorHint);
                    MaybeSpawnPowerUp(blk.Rect);
                }
                else
                {
                    _score += 2;
                    SpawnHitSparks(new Vec2(blk.Rect.X + blk.Rect.Width / 2f, blk.Rect.Y + blk.Rect.Height / 2f),
                        Color.FromArgb(220, 255, 255, 255), 10);
                }

                _blocks[i] = blk;
                hitBlock = true;
                break; // keep it crisp: one collision per frame
            }

            if (hitBlock)
            {
                // rebuild ball rect for subsequent tests if needed
                bRect = BallBounds();
            }

            // Update particles/powerups
            UpdateParticlesAndPowerups(dt, allowPowerups: true);

            // Level cleared?
            if (RemainingBlocks() == 0)
            {
                _state = GameState.LevelCleared;
                _levelClearedTimer = 1.1f;
                SpawnHitSparks(new Vec2(ClientSize.Width / 2f, ClientSize.Height / 3f),
                    Color.FromArgb(240, 255, 230, 120), 120);
                StickBallToPaddle();
            }
        }

        private void GameOver()
        {
            SaveHighScoreIfNeeded();
            _state = GameState.GameOver;

            // explosion confetti
            for (int i = 0; i < 220; i++)
                _particles.Add(Particle.Confetti(new Vec2(ClientSize.Width / 2f, ClientSize.Height / 2f), _rng));
        }

        private int RemainingBlocks()
        {
            int n = 0;
            for (int i = 0; i < _blocks.Count; i++)
                if (_blocks[i].Alive) n++;
            return n;
        }

        private RectangleF BallBounds()
        {
            return new RectangleF(_ballPos.X - _ballRadius, _ballPos.Y - _ballRadius, _ballRadius * 2f, _ballRadius * 2f);
        }

        private void ResolveRectOverlap(RectangleF rect, out Vec2 normal, out float push)
        {
            // uses current ball bounds overlap amounts
            RectangleF b = BallBounds();

            float overlapLeft = b.Right - rect.Left;
            float overlapRight = rect.Right - b.Left;
            float overlapTop = b.Bottom - rect.Top;
            float overlapBottom = rect.Bottom - b.Top;

            // smallest positive overlap
            push = overlapLeft;
            normal = new Vec2(-1, 0);

            if (overlapRight < push) { push = overlapRight; normal = new Vec2(1, 0); }
            if (overlapTop < push) { push = overlapTop; normal = new Vec2(0, -1); }
            if (overlapBottom < push) { push = overlapBottom; normal = new Vec2(0, 1); }

            // tiny bias to avoid sticking
            push = Math.Max(0.5f, push + 0.25f);
        }

        private void UpdateParticlesAndPowerups(float dt, bool allowPowerups)
        {
            // Particles
            for (int i = _particles.Count - 1; i >= 0; i--)
            {
                var p = _particles[i];
                p.Life -= dt;
                if (p.Life <= 0f) { _particles.RemoveAt(i); continue; }
                p.Vel += new Vec2(0, 650f) * dt; // gravity
                p.Pos += p.Vel * dt;
                _particles[i] = p;
            }

            if (!allowPowerups) return;

            // PowerUps
            for (int i = _powerUps.Count - 1; i >= 0; i--)
            {
                var pu = _powerUps[i];
                pu.Vel += new Vec2(0, 820f) * dt;
                pu.Pos += pu.Vel * dt;

                pu.Rect = new RectangleF(pu.Pos.X - pu.Size / 2f, pu.Pos.Y - pu.Size / 2f, pu.Size, pu.Size);

                if (pu.Rect.IntersectsWith(_paddle))
                {
                    ApplyPowerUp(pu.Type);
                    SpawnHitSparks(new Vec2(pu.Pos.X, pu.Pos.Y), Color.FromArgb(240, 140, 255, 180), 32);
                    _powerUps.RemoveAt(i);
                    continue;
                }

                if (pu.Pos.Y - pu.Size > ClientSize.Height + 30f)
                {
                    _powerUps.RemoveAt(i);
                    continue;
                }

                _powerUps[i] = pu;
            }
        }

        private void ApplyPowerUp(PowerUpType type)
        {
            switch (type)
            {
                case PowerUpType.Widen:
                    _widenTimer = 12f;
                    _score += 15;
                    break;
                case PowerUpType.Slow:
                    _slowTimer = 8f;
                    _score += 10;
                    break;
            }
        }

        private void MaybeSpawnPowerUp(RectangleF where)
        {
            // 14% chance
            if (_rng.NextDouble() > 0.14) return;

            var type = (_rng.Next(0, 2) == 0) ? PowerUpType.Widen : PowerUpType.Slow;
            var pu = new PowerUp
            {
                Type = type,
                Size = 18f,
                Pos = new Vec2(where.X + where.Width / 2f, where.Y + where.Height / 2f),
                Vel = new Vec2((float)(_rng.NextDouble() * 140 - 70), -120f),
            };
            pu.Rect = new RectangleF(pu.Pos.X - pu.Size / 2f, pu.Pos.Y - pu.Size / 2f, pu.Size, pu.Size);
            _powerUps.Add(pu);
        }

        private void SpawnBlockBurst(RectangleF r, Color c)
        {
            var center = new Vec2(r.X + r.Width / 2f, r.Y + r.Height / 2f);
            int n = 26 + _rng.Next(0, 14);
            for (int i = 0; i < n; i++)
            {
                _particles.Add(Particle.Burst(center, c, _rng));
            }
        }

        private void SpawnHitSparks(Vec2 pos, Color c, int n)
        {
            for (int i = 0; i < n; i++)
            {
                _particles.Add(Particle.Spark(pos, c, _rng));
            }
        }

        private void SpawnWallSparks(Vec2 pos, Vec2 dir)
        {
            for (int i = 0; i < 10; i++)
            {
                var p = Particle.Spark(pos, Color.FromArgb(220, 255, 255, 255), _rng);
                p.Vel += dir * (140f + (float)_rng.NextDouble() * 220f);
                _particles.Add(p);
            }
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            // keep paddle/ball sane after resize
            ResetLayout();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);

            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;

            DrawBackground(g);

            switch (_state)
            {
                case GameState.Title:
                    DrawTitle(g);
                    break;

                case GameState.Playing:
                case GameState.Paused:
                    DrawGame(g);
                    if (_state == GameState.Paused)
                        DrawCenteredPanel(g, "PAUSED", "Press P to resume");
                    break;

                case GameState.LevelCleared:
                    DrawGame(g);
                    DrawCenteredPanel(g, "LEVEL CLEARED", "Get ready...");
                    break;

                case GameState.GameOver:
                    DrawGame(g);
                    DrawCenteredPanel(g, "GAME OVER", "SPACE / Click: restart    ESC: exit");
                    break;
            }
        }

        private void DrawBackground(Graphics g)
        {
            Rectangle rc = ClientRectangle;

            using (var br = new LinearGradientBrush(rc, Color.FromArgb(18, 22, 40), Color.FromArgb(8, 10, 18), 90f))
                g.FillRectangle(br, rc);

            // subtle grid
            using (var p = new Pen(Color.FromArgb(18, 255, 255, 255), 1f))
            {
                int step = 36;
                for (int x = 0; x < rc.Width; x += step)
                    g.DrawLine(p, x, 0, x, rc.Height);
                for (int y = 0; y < rc.Height; y += step)
                    g.DrawLine(p, 0, y, rc.Width, y);
            }

            // vignette
            using (var path = new GraphicsPath())
            {
                path.AddEllipse(-rc.Width * 0.15f, -rc.Height * 0.15f, rc.Width * 1.3f, rc.Height * 1.3f);
                using (var pgb = new PathGradientBrush(path))
                {
                    pgb.CenterColor = Color.FromArgb(0, 0, 0, 0);
                    pgb.SurroundColors = new[] { Color.FromArgb(140, 0, 0, 0) };
                    g.FillRectangle(pgb, rc);
                }
            }
        }

        private void DrawTitle(Graphics g)
        {
            // Title image
            if (_imgTitle != null)
            {
                float w = Math.Min(ClientSize.Width * 0.78f, _imgTitle.Width);
                float scale = w / _imgTitle.Width;
                float h = _imgTitle.Height * scale;
                float x = (ClientSize.Width - w) / 2f;
                float y = ClientSize.Height * 0.12f;
                g.DrawImage(_imgTitle, x, y, w, h);
            }

            using (var fontBig = new Font("Segoe UI", 18f, FontStyle.Bold))
            using (var font = new Font("Segoe UI", 11f, FontStyle.Regular))
            using (var brush = new SolidBrush(Color.FromArgb(230, 255, 255, 255)))
            using (var brushDim = new SolidBrush(Color.FromArgb(180, 220, 220, 220)))
            {
                string hs = $"Highscore: {_highScore}";
                string hint = "SPACE / Click to start   |   Mouse to move   |   P to pause";

                var hsSize = g.MeasureString(hs, fontBig);
                g.DrawString(hs, fontBig, brush, (ClientSize.Width - hsSize.Width) / 2f, ClientSize.Height * 0.60f);

                var hintSize = g.MeasureString(hint, font);
                g.DrawString(hint, font, brushDim, (ClientSize.Width - hintSize.Width) / 2f, ClientSize.Height * 0.60f + 40f);
            }

            // a few idle particles
            if (_particles.Count < 40)
            {
                for (int i = 0; i < 2; i++)
                    _particles.Add(Particle.Confetti(new Vec2(ClientSize.Width / 2f, ClientSize.Height * 0.45f), _rng));
            }

            DrawParticles(g);
        }

        private void DrawGame(Graphics g)
        {
            DrawBlocks(g);
            DrawPaddle(g);
            DrawBall(g);
            DrawPowerUps(g);
            DrawParticles(g);
            DrawHud(g);
        }

        private void DrawBlocks(Graphics g)
        {
            for (int i = 0; i < _blocks.Count; i++)
            {
                var b = _blocks[i];
                if (!b.Alive) continue;

                Image img = null;
                if (b.Style >= 0 && b.Style < _imgBlocks.Count)
                    img = _imgBlocks[b.Style];

                if (img != null)
                {
                    g.DrawImage(img, b.Rect.X, b.Rect.Y, b.Rect.Width, b.Rect.Height);

                    // visually show toughness with a subtle overlay
                    if (b.HitsLeft >= 2)
                    {
                        using (var br = new SolidBrush(Color.FromArgb(45, 255, 255, 255)))
                            g.FillRectangle(br, b.Rect);
                    }
                    if (b.HitsLeft >= 3)
                    {
                        using (var p = new Pen(Color.FromArgb(110, 255, 255, 255), 2f))
                            g.DrawRectangle(p, b.Rect.X + 2, b.Rect.Y + 2, b.Rect.Width - 4, b.Rect.Height - 4);
                    }
                }
                else
                {
                    using (var br = new SolidBrush(b.ColorHint))
                        g.FillRectangle(br, b.Rect);
                    using (var p = new Pen(Color.Black, 1f))
                        g.DrawRectangle(p, b.Rect.X, b.Rect.Y, b.Rect.Width, b.Rect.Height);
                }
            }
        }

        private void DrawPaddle(Graphics g)
        {
            if (_imgPaddle != null)
                g.DrawImage(_imgPaddle, _paddle.X, _paddle.Y, _paddle.Width, _paddle.Height);
            else
            {
                using (var br = new SolidBrush(Color.White))
                    g.FillRectangle(br, _paddle);
            }
        }

        private void DrawBall(Graphics g)
        {
            RectangleF r = BallBounds();
            if (_imgBall != null)
                g.DrawImage(_imgBall, r.X, r.Y, r.Width, r.Height);
            else
            {
                using (var br = new SolidBrush(Color.White))
                    g.FillEllipse(br, r);
            }
        }

        private void DrawParticles(Graphics g)
        {
            for (int i = 0; i < _particles.Count; i++)
            {
                var p = _particles[i];
                float s = p.Size;
                using (var br = new SolidBrush(p.Color))
                {
                    if (p.Shape == ParticleShape.Circle)
                        g.FillEllipse(br, p.Pos.X - s / 2f, p.Pos.Y - s / 2f, s, s);
                    else
                        g.FillRectangle(br, p.Pos.X - s / 2f, p.Pos.Y - s / 2f, s, s);
                }
            }
        }

        private void DrawPowerUps(Graphics g)
        {
            for (int i = 0; i < _powerUps.Count; i++)
            {
                var pu = _powerUps[i];
                Color c = (pu.Type == PowerUpType.Widen) ? Color.FromArgb(230, 120, 255, 180) : Color.FromArgb(230, 140, 200, 255);

                using (var br = new SolidBrush(c))
                    g.FillEllipse(br, pu.Rect);

                using (var p = new Pen(Color.FromArgb(210, 20, 20, 20), 2f))
                    g.DrawEllipse(p, pu.Rect);

                string label = (pu.Type == PowerUpType.Widen) ? "W" : "S";
                using (var font = new Font("Segoe UI", 10f, FontStyle.Bold))
                using (var brText = new SolidBrush(Color.FromArgb(220, 10, 10, 10)))
                {
                    var sz = g.MeasureString(label, font);
                    g.DrawString(label, font, brText,
                        pu.Pos.X - sz.Width / 2f,
                        pu.Pos.Y - sz.Height / 2f - 1f);
                }
            }
        }

        private void DrawHud(Graphics g)
        {
            using (var font = new Font("Consolas", 11f, FontStyle.Bold))
            using (var br = new SolidBrush(Color.FromArgb(230, 240, 240, 240)))
            using (var brDim = new SolidBrush(Color.FromArgb(170, 220, 220, 220)))
            {
                string left = $"Score: {_score}   Lives: {_lives}   Level: {_level + 1}";
                g.DrawString(left, font, br, 12f, 10f);

                string right = $"High: {_highScore}";
                var sz = g.MeasureString(right, font);
                g.DrawString(right, font, brDim, ClientSize.Width - sz.Width - 12f, 10f);

                if (_widenTimer > 0f || _slowTimer > 0f)
                {
                    string fx = "";
                    if (_widenTimer > 0f) fx += $"Widen {Math.Ceiling(_widenTimer)}s  ";
                    if (_slowTimer > 0f) fx += $"Slow {Math.Ceiling(_slowTimer)}s";
                    g.DrawString(fx, font, brDim, 12f, 30f);
                }
            }
        }

        private void DrawCenteredPanel(Graphics g, string title, string subtitle)
        {
            float w = Math.Min(ClientSize.Width * 0.72f, 680f);
            float h = 140f;
            float x = (ClientSize.Width - w) / 2f;
            float y = ClientSize.Height * 0.42f - h / 2f;

            using (var br = new SolidBrush(Color.FromArgb(175, 0, 0, 0)))
                g.FillRoundedRectangle(br, x, y, w, h, 16f);

            using (var p = new Pen(Color.FromArgb(200, 255, 255, 255), 2f))
                g.DrawRoundedRectangle(p, x, y, w, h, 16f);

            using (var f1 = new Font("Segoe UI", 20f, FontStyle.Bold))
            using (var f2 = new Font("Segoe UI", 11f, FontStyle.Regular))
            using (var brText = new SolidBrush(Color.FromArgb(230, 255, 255, 255)))
            using (var brDim = new SolidBrush(Color.FromArgb(190, 220, 220, 220)))
            {
                var t1 = g.MeasureString(title, f1);
                g.DrawString(title, f1, brText, (ClientSize.Width - t1.Width) / 2f, y + 26f);

                var t2 = g.MeasureString(subtitle, f2);
                g.DrawString(subtitle, f2, brDim, (ClientSize.Width - t2.Width) / 2f, y + 74f);
            }
        }

        private void BuildLevel(int level)
        {
            _blocks.Clear();
            _powerUps.Clear();

            int cols = Math.Max(10, Math.Min(16, ClientSize.Width / 70));
            int rows = Math.Max(6, Math.Min(10, ClientSize.Height / 70));

            float marginX = 34f;
            float topY = 70f;

            float spacing = 6f;
            float usableW = ClientSize.Width - marginX * 2f;
            float blockW = (usableW - (cols - 1) * spacing) / cols;
            float blockH = Math.Max(16f, Math.Min(26f, ClientSize.Height / 24f));

            // Choose pattern set
            int pattern = level % 8;

            // deterministic per level
            var lvRng = new Random(9000 + level * 101);

            // Optional: text raster pattern for one level
            bool useText = (pattern == 7);
            bool[,] textMask = null;

            if (useText)
            {
                // Render "LEVEL N" into a small bitmap mask and translate to blocks
                int mw = cols;
                int mh = rows;
                textMask = RasterizeTextMask($"LEVEL {level + 1}", mw, mh);
            }

            for (int r = 0; r < rows; r++)
            {
                for (int c = 0; c < cols; c++)
                {
                    bool present;

                    if (useText)
                    {
                        present = textMask[r, c];
                    }
                    else
                    {
                        present = Pattern(pattern, r, c, rows, cols, lvRng);
                    }

                    if (!present) continue;

                    float x = marginX + c * (blockW + spacing);
                    float y = topY + r * (blockH + spacing);

                    int hits = 1;
                    if (level >= 3 && r < 2) hits = 2;
                    if (level >= 6 && r == 0) hits = 3;

                    int style = (r + c + level) % Math.Max(1, _imgBlocks.Count);
                    Color hint = StyleToColor(style);

                    _blocks.Add(new Block
                    {
                        Rect = new RectangleF(x, y, blockW, blockH),
                        HitsLeft = hits,
                        Alive = true,
                        Style = style,
                        ColorHint = hint
                    });
                }
            }

            // Give ball a nice fresh start
            StickBallToPaddle();
        }

        private static bool Pattern(int pattern, int r, int c, int rows, int cols, Random rng)
        {
            switch (pattern)
            {
                default:
                case 0: // full wall with small cutouts
                    return !(r == rows - 1 && (c % 3 == 1));
                case 1: // checkerboard
                    return ((r + c) % 2 == 0);
                case 2: // pyramid
                    {
                        int mid = cols / 2;
                        int width = 1 + r * 2;
                        int left = mid - width / 2;
                        int right = left + width - 1;
                        return (c >= left && c <= right);
                    }
                case 3: // hollow frame
                    return (r == 0 || r == rows - 1 || c == 0 || c == cols - 1);
                case 4: // diagonal stripes
                    return ((r * 2 + c) % 4 != 1);
                case 5: // wave cutouts
                    return ((r + (int)(Math.Sin(c * 0.8) * 2.0 + 2.5)) % 3 != 0);
                case 6: // random holes (stable by level rng)
                    return rng.NextDouble() > 0.22;
            }
        }

        private static bool[,] RasterizeTextMask(string text, int cols, int rows)
        {
            // draw into bitmap then sample to grid
            using (var bmp = new Bitmap(320, 140))
            using (var g = Graphics.FromImage(bmp))
            {
                g.Clear(Color.Black);
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;

                using (var font = new Font("Segoe UI", 48f, FontStyle.Bold))
                using (var br = new SolidBrush(Color.White))
                {
                    var sz = g.MeasureString(text, font);
                    float x = (bmp.Width - sz.Width) / 2f;
                    float y = (bmp.Height - sz.Height) / 2f - 6f;
                    g.DrawString(text, font, br, x, y);
                }

                bool[,] mask = new bool[rows, cols];

                for (int r = 0; r < rows; r++)
                {
                    for (int c = 0; c < cols; c++)
                    {
                        // sample center of each cell
                        int sx = (int)((c + 0.5) / cols * bmp.Width);
                        int sy = (int)((r + 0.5) / rows * bmp.Height);
                        Color px = bmp.GetPixel(ClampInt(sx, 0, bmp.Width - 1), ClampInt(sy, 0, bmp.Height - 1));

                        // threshold
                        mask[r, c] = (px.R + px.G + px.B) > 60;
                    }
                }

                return mask;
            }
        }

        private static int ClampInt(int v, int min, int max)
        {
            if (v < min) return min;
            if (v > max) return max;
            return v;
        }

        private static float Clamp(float v, float min, float max)
        {
            if (v < min) return min;
            if (v > max) return max;
            return v;
        }

        private Color StyleToColor(int style)
        {
            // purely for fallback drawing / particle hints
            Color[] palette =
            {
                Color.FromArgb(240, 255, 120, 120),
                Color.FromArgb(240, 255, 190, 120),
                Color.FromArgb(240, 255, 240, 120),
                Color.FromArgb(240, 140, 255, 180),
                Color.FromArgb(240, 140, 200, 255),
                Color.FromArgb(240, 210, 150, 255),
            };
            if (palette.Length == 0) return Color.White;
            return palette[Math.Abs(style) % palette.Length];
        }

        // ========= Data folder & asset generation =========

        private void EnsureDataAssets()
        {
            Directory.CreateDirectory(_dataDir);

            // Highscore file
            if (!File.Exists(_highScorePath))
                File.WriteAllText(_highScorePath, "0");

            // Images
            CreatePngIfMissing(Path.Combine(_dataDir, "paddle.png"), 256, 32, DrawPaddlePng);
            CreatePngIfMissing(Path.Combine(_dataDir, "ball.png"), 64, 64, DrawBallPng);
            CreatePngIfMissing(Path.Combine(_dataDir, "title.png"), 900, 340, DrawTitlePng);

            // Block variants
            CreatePngIfMissing(Path.Combine(_dataDir, "block_0.png"), 128, 40, g => DrawBlockPng(g, Color.FromArgb(255, 120, 120)));
            CreatePngIfMissing(Path.Combine(_dataDir, "block_1.png"), 128, 40, g => DrawBlockPng(g, Color.FromArgb(255, 190, 120)));
            CreatePngIfMissing(Path.Combine(_dataDir, "block_2.png"), 128, 40, g => DrawBlockPng(g, Color.FromArgb(255, 240, 120)));
            CreatePngIfMissing(Path.Combine(_dataDir, "block_3.png"), 128, 40, g => DrawBlockPng(g, Color.FromArgb(140, 255, 180)));
            CreatePngIfMissing(Path.Combine(_dataDir, "block_4.png"), 128, 40, g => DrawBlockPng(g, Color.FromArgb(140, 200, 255)));
            CreatePngIfMissing(Path.Combine(_dataDir, "block_5.png"), 128, 40, g => DrawBlockPng(g, Color.FromArgb(210, 150, 255)));
        }

        private static void CreatePngIfMissing(string path, int w, int h, Action<Graphics> draw)
        {
            if (File.Exists(path)) return;

            try
            {
                using (var bmp = new Bitmap(w, h))
                using (var g = Graphics.FromImage(bmp))
                {
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.Clear(Color.Transparent);
                    draw(g);
                    bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png);
                }
            }
            catch
            {
                // If saving fails (permissions etc.), just continue; game has fallbacks.
            }
        }

        private static void DrawPaddlePng(Graphics g)
        {
            var rc = new RectangleF(0, 0, 256, 32);

            using (var br = new LinearGradientBrush(rc, Color.FromArgb(220, 245, 245, 245), Color.FromArgb(220, 120, 120, 130), 90f))
                g.FillRoundedRectangle(br, rc.X + 2, rc.Y + 4, rc.Width - 4, rc.Height - 8, 14f);

            using (var p = new Pen(Color.FromArgb(240, 10, 10, 10), 3f))
                g.DrawRoundedRectangle(p, rc.X + 2, rc.Y + 4, rc.Width - 4, rc.Height - 8, 14f);

            // little neon stripe
            using (var br = new SolidBrush(Color.FromArgb(160, 120, 255, 180)))
                g.FillRoundedRectangle(br, rc.X + 18, rc.Y + 10, rc.Width - 36, 6, 4f);
        }

        private static void DrawBallPng(Graphics g)
        {
            var rc = new RectangleF(0, 0, 64, 64);
            using (var path = new GraphicsPath())
            {
                path.AddEllipse(4, 4, 56, 56);
                using (var pgb = new PathGradientBrush(path))
                {
                    pgb.CenterColor = Color.FromArgb(255, 255, 255, 255);
                    pgb.SurroundColors = new[] { Color.FromArgb(255, 90, 160, 255) };
                    g.FillEllipse(pgb, 4, 4, 56, 56);
                }
            }

            using (var p = new Pen(Color.FromArgb(220, 10, 10, 10), 3f))
                g.DrawEllipse(p, 4, 4, 56, 56);

            using (var br = new SolidBrush(Color.FromArgb(160, 255, 255, 255)))
                g.FillEllipse(br, 16, 14, 14, 14);
        }

        private static void DrawBlockPng(Graphics g, Color baseColor)
        {
            var rc = new RectangleF(0, 0, 128, 40);

            // glossy gradient
            using (var br = new LinearGradientBrush(rc, Lighten(baseColor, 0.35f), Darken(baseColor, 0.25f), 90f))
                g.FillRoundedRectangle(br, 2, 4, 124, 32, 10f);

            // highlight band
            using (var br = new SolidBrush(Color.FromArgb(80, 255, 255, 255)))
                g.FillRoundedRectangle(br, 10, 8, 108, 10, 6f);

            using (var p = new Pen(Color.FromArgb(220, 10, 10, 10), 2f))
                g.DrawRoundedRectangle(p, 2, 4, 124, 32, 10f);
        }

        private static void DrawTitlePng(Graphics g)
        {
            var rc = new Rectangle(0, 0, 900, 340);

            using (var br = new LinearGradientBrush(rc, Color.FromArgb(18, 22, 40), Color.FromArgb(6, 8, 16), 90f))
                g.FillRectangle(br, rc);

            // scanlines
            using (var p = new Pen(Color.FromArgb(18, 255, 255, 255), 1f))
            {
                for (int y = 0; y < rc.Height; y += 3)
                    g.DrawLine(p, 0, y, rc.Width, y);
            }

            // big text w/ shadow
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
            using (var font = new Font("Segoe UI", 82f, FontStyle.Bold))
            using (var shadow = new SolidBrush(Color.FromArgb(160, 0, 0, 0)))
            using (var br = new SolidBrush(Color.FromArgb(240, 255, 240, 120)))
            using (var br2 = new SolidBrush(Color.FromArgb(230, 140, 200, 255)))
            {
                string title = "BREAKOUT";
                var sz = g.MeasureString(title, font);

                float x = (rc.Width - sz.Width) / 2f;
                float y = 78f;

                g.DrawString(title, font, shadow, x + 6f, y + 8f);
                g.DrawString(title, font, br, x, y);

                using (var font2 = new Font("Segoe UI", 18f, FontStyle.Bold))
                {
                    string sub = "github.com/zeittresor";
                    var s2 = g.MeasureString(sub, font2);
                    g.DrawString(sub, font2, br2, (rc.Width - s2.Width) / 2f, y + 120f);
                }
            }

            // decorative arcs
            using (var p = new Pen(Color.FromArgb(120, 140, 255, 180), 6f))
                g.DrawArc(p, 60, 40, 200, 200, 210, 240);

            using (var p = new Pen(Color.FromArgb(120, 140, 200, 255), 6f))
                g.DrawArc(p, 640, 80, 220, 220, -30, 240);
        }

        private void LoadAssets()
        {
            SafeDisposeImages();
            _imgBlocks.Clear();

            _imgPaddle = TryLoadImage(Path.Combine(_dataDir, "paddle.png"));
            _imgBall = TryLoadImage(Path.Combine(_dataDir, "ball.png"));
            _imgTitle = TryLoadImage(Path.Combine(_dataDir, "title.png"));

            for (int i = 0; i < 6; i++)
            {
                var img = TryLoadImage(Path.Combine(_dataDir, $"block_{i}.png"));
                if (img != null) _imgBlocks.Add(img);
            }

            // Ensure at least one style index exists so modulo doesn't crash
            if (_imgBlocks.Count == 0)
                _imgBlocks.Add(null);
        }

        private static Image TryLoadImage(string path)
        {
            try
            {
                if (!File.Exists(path)) return null;

                // Avoid file lock: load into memory
                byte[] bytes = File.ReadAllBytes(path);
                using (var ms = new MemoryStream(bytes))
                {
                    return Image.FromStream(ms);
                }
            }
            catch
            {
                return null;
            }
        }

        private void SafeDisposeImages()
        {
            try { _imgPaddle?.Dispose(); } catch { }
            try { _imgBall?.Dispose(); } catch { }
            try { _imgTitle?.Dispose(); } catch { }
            for (int i = 0; i < _imgBlocks.Count; i++)
            {
                try { _imgBlocks[i]?.Dispose(); } catch { }
            }
        }

        private void LoadHighScore()
        {
            try
            {
                if (File.Exists(_highScorePath))
                {
                    string s = File.ReadAllText(_highScorePath).Trim();
                    int v;
                    if (int.TryParse(s, out v)) _highScore = Math.Max(0, v);
                }
            }
            catch
            {
                _highScore = 0;
            }
        }

        private void SaveHighScoreIfNeeded()
        {
            try
            {
                if (_score > _highScore) _highScore = _score;
                File.WriteAllText(_highScorePath, _highScore.ToString());
            }
            catch
            {
                // ignore
            }
        }

        // ========= Utility: color =========

        private static Color Lighten(Color c, float amount)
        {
            int r = ClampInt((int)(c.R + (255 - c.R) * amount), 0, 255);
            int g = ClampInt((int)(c.G + (255 - c.G) * amount), 0, 255);
            int b = ClampInt((int)(c.B + (255 - c.B) * amount), 0, 255);
            return Color.FromArgb(c.A, r, g, b);
        }

        private static Color Darken(Color c, float amount)
        {
            int r = ClampInt((int)(c.R * (1f - amount)), 0, 255);
            int g = ClampInt((int)(c.G * (1f - amount)), 0, 255);
            int b = ClampInt((int)(c.B * (1f - amount)), 0, 255);
            return Color.FromArgb(c.A, r, g, b);
        }
    }

    // ========= Data structs =========

    internal struct Vec2
    {
        public float X;
        public float Y;

        public Vec2(float x, float y) { X = x; Y = y; }

        public static Vec2 operator +(Vec2 a, Vec2 b) { return new Vec2(a.X + b.X, a.Y + b.Y); }
        public static Vec2 operator -(Vec2 a, Vec2 b) { return new Vec2(a.X - b.X, a.Y - b.Y); }
        public static Vec2 operator *(Vec2 a, float s) { return new Vec2(a.X * s, a.Y * s); }

        public float Length() { return (float)Math.Sqrt(X * X + Y * Y); }
    }

    internal struct Block
    {
        public RectangleF Rect;
        public int HitsLeft;
        public bool Alive;
        public int Style;
        public Color ColorHint;
    }

    internal enum ParticleShape { Circle, Square }

    internal struct Particle
    {
        public Vec2 Pos;
        public Vec2 Vel;
        public float Life;
        public float Size;
        public Color Color;
        public ParticleShape Shape;

        public static Particle Spark(Vec2 at, Color c, Random rng)
        {
            double a = rng.NextDouble() * Math.PI * 2.0;
            float sp = 140f + (float)rng.NextDouble() * 420f;
            return new Particle
            {
                Pos = at,
                Vel = new Vec2((float)Math.Cos(a) * sp, (float)Math.Sin(a) * sp),
                Life = 0.35f + (float)rng.NextDouble() * 0.35f,
                Size = 2f + (float)rng.NextDouble() * 3f,
                Color = c,
                Shape = ParticleShape.Circle
            };
        }

        public static Particle Burst(Vec2 at, Color c, Random rng)
        {
            double a = rng.NextDouble() * Math.PI * 2.0;
            float sp = 120f + (float)rng.NextDouble() * 520f;
            return new Particle
            {
                Pos = at,
                Vel = new Vec2((float)Math.Cos(a) * sp, (float)Math.Sin(a) * sp),
                Life = 0.55f + (float)rng.NextDouble() * 0.55f,
                Size = 3f + (float)rng.NextDouble() * 4f,
                Color = Color.FromArgb(220, c.R, c.G, c.B),
                Shape = (rng.Next(0, 2) == 0) ? ParticleShape.Circle : ParticleShape.Square
            };
        }

        public static Particle Confetti(Vec2 at, Random rng)
        {
            Color[] pal =
            {
                Color.FromArgb(220, 255, 120, 120),
                Color.FromArgb(220, 255, 190, 120),
                Color.FromArgb(220, 255, 240, 120),
                Color.FromArgb(220, 140, 255, 180),
                Color.FromArgb(220, 140, 200, 255),
                Color.FromArgb(220, 210, 150, 255)
            };

            double a = rng.NextDouble() * Math.PI * 2.0;
            float sp = 60f + (float)rng.NextDouble() * 220f;
            return new Particle
            {
                Pos = at + new Vec2((float)(rng.NextDouble() * 240 - 120), (float)(rng.NextDouble() * 80 - 40)),
                Vel = new Vec2((float)Math.Cos(a) * sp, (float)Math.Sin(a) * sp - 120f),
                Life = 0.7f + (float)rng.NextDouble() * 1.1f,
                Size = 3f + (float)rng.NextDouble() * 5f,
                Color = pal[rng.Next(0, pal.Length)],
                Shape = ParticleShape.Square
            };
        }
    }

    internal enum PowerUpType { Widen, Slow }

    internal struct PowerUp
    {
        public PowerUpType Type;
        public Vec2 Pos;
        public Vec2 Vel;
        public float Size;
        public RectangleF Rect;
    }

    // ========= Graphics helpers =========

    internal static class GraphicsExtensions
    {
        public static void FillRoundedRectangle(this Graphics g, Brush brush, float x, float y, float w, float h, float r)
        {
            using (var path = RoundedRect(x, y, w, h, r))
                g.FillPath(brush, path);
        }

        public static void DrawRoundedRectangle(this Graphics g, Pen pen, float x, float y, float w, float h, float r)
        {
            using (var path = RoundedRect(x, y, w, h, r))
                g.DrawPath(pen, path);
        }

        private static GraphicsPath RoundedRect(float x, float y, float w, float h, float r)
        {
            float d = r * 2f;
            var path = new GraphicsPath();
            path.AddArc(x, y, d, d, 180, 90);
            path.AddArc(x + w - d, y, d, d, 270, 90);
            path.AddArc(x + w - d, y + h - d, d, d, 0, 90);
            path.AddArc(x, y + h - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }
}

// StarfieldDemo.cs
// .NET 6+ WinForms Single-File Example

using System;
using System.Drawing;
using System.Windows.Forms;

namespace StarfieldDemo
{
    internal static class Program
    {
        [STAThread]
        static void Main()
        {
            ApplicationConfiguration.Initialize();
            Application.Run(new MainForm());
        }
    }

    public sealed class MainForm : Form
    {
        private readonly Button _btnShow;

        public MainForm()
        {
            Text = "Starfield Launcher";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(420, 160);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;

            _btnShow = new Button
            {
                Text = "show starfield",
                Font = new Font("Segoe UI", 12f, FontStyle.Regular),
                Size = new Size(200, 48),
                Location = new Point((ClientSize.Width - 200) / 2, (ClientSize.Height - 48) / 2),
                Anchor = AnchorStyles.None
            };

            _btnShow.Click += (_, __) =>
            {
                var sf = new StarfieldForm();
                sf.Show(); // neues Fenster
                sf.Activate();
            };

            Controls.Add(_btnShow);
        }
    }

    public sealed class StarfieldForm : Form
    {
        private readonly Timer _timer;
        private readonly Random _rng = new Random();

        private Star[] _stars = Array.Empty<Star>();

        // Tuning
        private int _starCount = 900;
        private float _speed = 1.35f;     // höher = schneller
        private float _fov = 520f;        // Projektion: "Zoom"
        private bool _streaks = true;

        private int _cx, _cy;

        public StarfieldForm()
        {
            Text = "Starfield";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(900, 600);
            BackColor = Color.Black;

            // Flacker-frei
            SetStyle(ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.UserPaint |
                     ControlStyles.OptimizedDoubleBuffer, true);
            DoubleBuffered = true;

            KeyPreview = true;
            KeyDown += StarfieldForm_KeyDown;

            _timer = new Timer { Interval = 16 }; // ~60 FPS
            _timer.Tick += (_, __) =>
            {
                UpdateStars();
                Invalidate();
            };

            Shown += (_, __) =>
            {
                ResizeCenter();
                InitStars();
                _timer.Start();
            };

            Resize += (_, __) => ResizeCenter();

            FormClosed += (_, __) => _timer.Stop();
        }

        private void StarfieldForm_KeyDown(object? sender, KeyEventArgs e)
        {
            // Kleine Hotkeys, falls du beim Testen schnell drehen willst:
            // + / - = Speed, S = Streaks togglen, R = Reset
            if (e.KeyCode == Keys.Add || e.KeyCode == Keys.Oemplus) _speed *= 1.12f;
            if (e.KeyCode == Keys.Subtract || e.KeyCode == Keys.OemMinus) _speed /= 1.12f;

            if (e.KeyCode == Keys.S) _streaks = !_streaks;

            if (e.KeyCode == Keys.R)
            {
                InitStars();
            }

            if (e.KeyCode == Keys.Escape)
            {
                Close();
            }
        }

        private void ResizeCenter()
        {
            _cx = ClientSize.Width / 2;
            _cy = ClientSize.Height / 2;
        }

        private void InitStars()
        {
            _stars = new Star[_starCount];
            for (int i = 0; i < _stars.Length; i++)
            {
                _stars[i] = NewStar(spawnAtFront: true);
            }
        }

        private Star NewStar(bool spawnAtFront)
        {
            // x/y im Raum: -1..1 (quadratisch), z: 0..1 (Tiefe)
            // spawnAtFront => z nahe 1 (weit hinten), damit es "reinfliegt"
            float x = (float)(_rng.NextDouble() * 2.0 - 1.0);
            float y = (float)(_rng.NextDouble() * 2.0 - 1.0);
            float z = spawnAtFront ? 0.75f + (float)(_rng.NextDouble() * 0.25f) : (float)(_rng.NextDouble());

            // kleine Streuung: mehr Sterne zur Mitte hin wirkt “klassischer”
            // optional: mit leichter non-linear distribution
            x = SignedPow(x, 1.15f);
            y = SignedPow(y, 1.15f);

            return new Star(x, y, z, _cx, _cy);
        }

        private static float SignedPow(float v, float p)
        {
            float s = MathF.Sign(v);
            return s * MathF.Pow(MathF.Abs(v), p);
        }

        private void UpdateStars()
        {
            if (_stars.Length == 0) return;

            float dz = 0.018f * _speed; // pro Frame

            for (int i = 0; i < _stars.Length; i++)
            {
                ref Star s = ref _stars[i];

                // vorherige Bildschirmposition merken
                s.PrevSX = s.SX;
                s.PrevSY = s.SY;

                s.Z -= dz;

                // Wenn "zu nah" (oder vorbei) -> neu hinten spawnen
                if (s.Z <= 0.03f)
                {
                    s = NewStar(spawnAtFront: true);
                    continue;
                }

                // projizieren
                Project(ref s);

                // Wenn außerhalb -> neu (macht den Flow clean)
                if (s.SX < -100 || s.SX > ClientSize.Width + 100 ||
                    s.SY < -100 || s.SY > ClientSize.Height + 100)
                {
                    s = NewStar(spawnAtFront: true);
                    continue;
                }
            }
        }

        private void Project(ref Star s)
        {
            // Perspektive: screen = (x/z)*fov + center
            float invZ = 1.0f / s.Z;
            s.SX = _cx + (s.X * invZ) * _fov;
            s.SY = _cy + (s.Y * invZ) * _fov;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            // Hintergrund
            e.Graphics.Clear(Color.Black);
            e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.None;

            // Sterne
            for (int i = 0; i < _stars.Length; i++)
            {
                ref Star s = ref _stars[i];

                // Helligkeit/Größe abhängig von Z (näher = heller/größer)
                float t = 1.0f - s.Z; // 0..~1
                int b = ClampToByte(60 + (int)(195 * t)); // 60..255

                // kleiner Radius
                float radius = 0.8f + 2.2f * t;

                using var pen = new Pen(Color.FromArgb(b, b, b), 1f);
                using var brush = new SolidBrush(Color.FromArgb(b, b, b));

                if (_streaks)
                {
                    // Linie von vorher nach jetzt (Streak)
                    // Wenn Prev nicht gesetzt (0), dann nur Punkt
                    if (s.PrevSX != 0 || s.PrevSY != 0)
                    {
                        e.Graphics.DrawLine(pen, s.PrevSX, s.PrevSY, s.SX, s.SY);
                    }
                }

                // Punkt/kleiner Kreis
                e.Graphics.FillEllipse(brush, s.SX - radius * 0.5f, s.SY - radius * 0.5f, radius, radius);
            }

            // HUD mini
            using var hudBrush = new SolidBrush(Color.FromArgb(200, 200, 200));
            string hud = $"Stars: {_starCount}   Speed: {_speed:0.00}   Streaks: {(_streaks ? "ON" : "OFF")}   (+/- speed, S streaks, R reset, ESC close)";
            e.Graphics.DrawString(hud, Font, hudBrush, 10, 10);
        }

        private static int ClampToByte(int v) => v < 0 ? 0 : (v > 255 ? 255 : v);

        private struct Star
        {
            public float X, Y, Z;
            public float SX, SY;
            public float PrevSX, PrevSY;

            public Star(float x, float y, float z, int cx, int cy)
            {
                X = x; Y = y; Z = z;
                SX = cx; SY = cy;
                PrevSX = 0; PrevSY = 0;
            }
        }
    }
}

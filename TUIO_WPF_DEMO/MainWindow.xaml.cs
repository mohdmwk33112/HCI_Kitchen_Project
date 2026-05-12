using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using TUIO;
using System.Net.Sockets; // Add this for TCP Sockets
using System.Text;        // Add this for Encoding
using System.Threading.Tasks; // Add this for Tasks
using System.Text.Json; // Add this for JSON parsing

namespace TUIO_WPF_DEMO
{
    public partial class MainWindow : Window, TuioListener
    {
        private TuioClient client;
        private TcpClient pythonClient;
        private NetworkStream stream;

        // Track UI elements by their TUIO SessionID
        private Dictionary<long, FrameworkElement> cursorElements = new Dictionary<long, FrameworkElement>();
        private Dictionary<long, FrameworkElement> objectElements = new Dictionary<long, FrameworkElement>();
        private Dictionary<long, FrameworkElement> blobElements = new Dictionary<long, FrameworkElement>();
        
        // Cooking Menu State (Persistent)
        private FrameworkElement cookingMenu;
        private List<Path> innerSegmentList;
        private List<Path> outerSegmentList;
        private long activeMenuSessionId = -1;
        private string activeSubMenu = "None"; // "None", "Timer", "Heat", "Recipes"
        private DateTime segmentHoverStart;
        private int lastHoveredSegment = -1;
        private string lastHoveredRing = "None"; // "Inner" or "Outer"
        private Point menuFixedCenter;
        
        private System.Windows.Threading.DispatcherTimer kitchenTimer;
        private int remainingSeconds = 0;

        public MainWindow()
        {
            // Register encoding for TUIO protocol compatibility
            System.Text.Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);

            InitializeComponent();

            client = new TuioClient(3333);
            client.addTuioListener(this);
            client.connect();

            this.Closing += (s, e) => {
                client.disconnect();
                if (pythonClient != null) pythonClient.Close();
            };
            GetCurrentTimeContext();
            string labelText = $"({GetCurrentTimeContext()})";

            ConnectToPythonServer();
        }

        private async void ConnectToPythonServer()
        {
            try
            {
                // 1. Connect to the IP and Port from your lab code (localhost:5000)
                pythonClient = new TcpClient();
                await pythonClient.ConnectAsync("127.0.0.1", 65434);
                stream = pythonClient.GetStream();

                System.Diagnostics.Debug.WriteLine("Connected to Python Server!");
                // 2. Start a background task to listen for messages from Python
                _ = Task.Run(() => ListenToPython());
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine("Python Server Error: " + ex.Message);
            }
        }

        private void ListenToPython()
        {
            try
            {
                using (var reader = new System.IO.StreamReader(stream, Encoding.UTF8, true, 1024, true))
                {
                    while (pythonClient != null && pythonClient.Connected)
                    {
                        string message = reader.ReadLine();
                        if (message == null) break; // Disconnected

                        System.Diagnostics.Debug.WriteLine("Message from Python: " + message);
                        
                        // Process the message on the UI thread
                        Dispatcher.Invoke(() => HandleServerMessage(message));
                    }
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine("Listen Error: " + ex.Message);
            }
        }

        private void HandleServerMessage(string message)
        {
            if (message.StartsWith("{"))
            {
                // Parse JSON Gesture
                try
                {
                    var gestureData = JsonSerializer.Deserialize<Dictionary<string, object>>(message);
                    if (gestureData.ContainsKey("gesture"))
                    {
                        string gesture = gestureData["gesture"].ToString();
                        double confidence = double.Parse(gestureData["confidence"].ToString());
                        
                        // Parse X and Y if available
                        double normX = 0.5;
                        double normY = 0.5;
                        if (gestureData.ContainsKey("x") && gestureData.ContainsKey("y"))
                        {
                            normX = double.Parse(gestureData["x"].ToString());
                            normY = double.Parse(gestureData["y"].ToString());
                        }

                        ContextDisplay.Text = $"Context: Gesture Detected -> {gesture} ({confidence})";
                        
                        // Log gesture to server DB
                        SendToServer($"LOG;gesture;{{\"gesture\":\"{gesture}\"}}");

                        // Add application logic for gestures here
                        if (gesture == "Swipe Left") { /* Go to previous step */ }
                        else if (gesture == "Swipe Right") { SendToServer("NEXT"); /* Go to next step */ }
                        else if (gesture == "Click") { 
                            // Emulate TUIO click logic or menu selection
                            CheckMenuSelection((float)normX, (float)normY); 
                        }
                        else if (gesture == "Circle")
                        {
                            // Open circular menu at the hand cursor location
                            if (cookingMenu == null)
                            {
                                cookingMenu = CreateCircularMenu();
                                MainCanvas.Children.Add(cookingMenu);
                                UpdateElementPosition(cookingMenu, (float)normX, (float)normY);
                                
                                double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
                                double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
                                menuFixedCenter = new Point(normX * canvasW, normY * canvasH);
                            }
                        }
                        else if (gesture == "L Shape")
                        {
                            // Pause timers and ask for logout confirmation
                            var result = MessageBox.Show(
                                "Are you sure you want to log out?",
                                "Logout Confirmation",
                                MessageBoxButton.YesNo,
                                MessageBoxImage.Question);
                                
                            if (result == MessageBoxResult.Yes)
                            {
                                ContextDisplay.Text = "Context: Logging out...";
                                RemoveActiveMenu();
                                SendToServer("LOGOUT");
                            }
                        }
                    }
                }
                catch (Exception ex) { System.Diagnostics.Debug.WriteLine("JSON Error: " + ex.Message); }
            }
            else if (message.StartsWith("login_success"))
            {
                string[] parts = message.Split(';');
                string userName = parts.Length > 1 ? parts[1] : "Unknown";
                ContextDisplay.Text = $"Context: Welcome, {userName}!";
                
                // Example: Request Recipe ID 1 once logged in
                SendToServer("RECIPE_ID;1");
            }
            else if (message.StartsWith("login_failed"))
            {
                ContextDisplay.Text = "Context: Face Login Failed. " + message;
            }
            else if (message.StartsWith("step"))
            {
                // Format: step;index;total;instruction
                string[] parts = message.Split(';');
                if (parts.Length >= 4)
                {
                    ContextDisplay.Text = $"Context: Step {parts[1]}/{parts[2]}: {parts[3]}";
                }
            }
            else if (message == "session_done")
            {
                ContextDisplay.Text = "Context: Recipe Completed! Evaluation ready.";
                // Submit mock evaluation
                SendToServer("EVAL;300;0;20.5;Great recipe");
            }
            else if (message.StartsWith("logout_success"))
            {
                ContextDisplay.Text = "Context: Logged out successfully. Waiting for Face Login...";
            }
            else if (message.StartsWith("error"))
            {
                ContextDisplay.Text = "Context: Server Error - " + message;
            }
            else if (message.Contains(";") && !message.StartsWith("gestures_"))
            {
                // Handle recipe header (title;scenario;ingredients...)
                string[] parts = message.Split(';');
                ContextDisplay.Text = $"Context: Recipe '{parts[0]}' loaded.";
                
                // Automatically confirm to start receiving steps
                SendToServer("CONFIRM");
                
                // Start gestures when cooking begins
                SendToServer("START_GESTURES");
            }
        }

        private void SendToServer(string message)
        {
            if (pythonClient != null && pythonClient.Connected && stream != null)
            {
                try
                {
                    byte[] data = Encoding.UTF8.GetBytes(message + "\n");
                    stream.Write(data, 0, data.Length);
                    System.Diagnostics.Debug.WriteLine("Sent to Python: " + message);
                }
                catch (Exception ex) { System.Diagnostics.Debug.WriteLine("Send Error: " + ex.Message); }
            }
        }

        #region TUIO Cursors (Fingers)
        public void addTuioCursor(TuioCursor c)
        {
            Dispatcher.Invoke(() => {
                Grid container = CreateContainer(20, 20, Brushes.Magenta, Brushes.Blue, true, c.CursorID.ToString());
                cursorElements[c.SessionID] = container;
                MainCanvas.Children.Add(container);
                UpdateElementPosition(container, c.X, c.Y);
                CheckMenuSelection(c.X, c.Y);
            });
        }

        public void updateTuioCursor(TuioCursor c)
        {
            Dispatcher.Invoke(() => {
                if (cursorElements.ContainsKey(c.SessionID))
                {
                    UpdateElementPosition(cursorElements[c.SessionID], c.X, c.Y);
                    CheckMenuSelection(c.X, c.Y);
                }
            });
        }

        public void removeTuioCursor(TuioCursor c)
        {
            Dispatcher.Invoke(() => {
                if (cursorElements.ContainsKey(c.SessionID))
                {
                    MainCanvas.Children.Remove(cursorElements[c.SessionID]);
                    cursorElements.Remove(c.SessionID);
                }
            });
        }
        #endregion

        #region TUIO Objects (Fiducials)
        public void addTuioObject(TuioObject o)
        {
            Dispatcher.Invoke(() => {
                Grid container = CreateContainer(50, 50, new SolidColorBrush(Color.FromRgb(64, 0, 0)), Brushes.White, false, o.SymbolID.ToString());
                objectElements[o.SessionID] = container;
                MainCanvas.Children.Add(container);
                UpdateElementPosition(container, o.X, o.Y, o.Angle);

                if (o.SymbolID == 0)
                {
                    if (cookingMenu == null) // Only create if not exists
                    {
                        cookingMenu = CreateCircularMenu();
                        MainCanvas.Children.Add(cookingMenu);
                        UpdateElementPosition(cookingMenu, o.X, o.Y);
                        
                        double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
                        double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
                        menuFixedCenter = new Point(o.X * canvasW, o.Y * canvasH);
                    }
                    activeMenuSessionId = o.SessionID; // Always track the current session ID
                }
            });
        }

        // 1. Define how sensitive you want it to be (0.1 to 0.5 is usually good)
        private float rotationThreshold = 0.2f;

        public void updateTuioObject(TuioObject o)
        {
            Dispatcher.Invoke(() => {
                if (objectElements.ContainsKey(o.SessionID))
                {
                    UpdateElementPosition(objectElements[o.SessionID], o.X, o.Y, o.Angle);

                    // 2. Check if the speed is higher than the threshold
                    if (o.RotationSpeed > rotationThreshold)
                    {
                        System.Diagnostics.Debug.WriteLine("Action: Rotating RIGHT");
                        // Trigger your Right-Rotation function here
                    }
                    else if (o.RotationSpeed < -rotationThreshold)
                    {
                        System.Diagnostics.Debug.WriteLine("Action: Rotating LEFT");
                        // Trigger your Left-Rotation function here
                    }
                    else
                    {
                        // This is the "Center" or Neutral state
                        System.Diagnostics.Debug.WriteLine("State: IDLE / CENTER");
                    }

                    if (o.SymbolID == 0 && cookingMenu != null)
                    {
                        // Update session ID if it changed (e.g. reappeared)
                        activeMenuSessionId = o.SessionID;
                        CheckMenuSelection(o.X, o.Y);
                    }
                }
            });
        }

        private void StartKitchenTimer(int minutes)
        {
            if (kitchenTimer == null)
            {
                kitchenTimer = new System.Windows.Threading.DispatcherTimer();
                kitchenTimer.Interval = TimeSpan.FromSeconds(1);
                kitchenTimer.Tick += (s, e) => {
                    if (remainingSeconds > 0)
                    {
                        remainingSeconds--;
                        UpdateTimerDisplay();
                    }
                    else
                    {
                        kitchenTimer.Stop();
                        ContextDisplay.Text = "Context: TIMER FINISHED! 🛎️";
                        System.Media.SystemSounds.Exclamation.Play();
                    }
                };
            }

            remainingSeconds = minutes * 60;
            kitchenTimer.Start();
            UpdateTimerDisplay();
            ContextDisplay.Text = $"Context: Timer set for {minutes}m";
        }

        private void UpdateTimerDisplay()
        {
            int m = remainingSeconds / 60;
            int s = remainingSeconds % 60;
            TimerDisplay.Text = string.Format("{0:D2}:{1:D2}", m, s);
        }

        private string GetCurrentTimeContext()
        {
            int hour = DateTime.Now.Hour;
            if (hour >= 5 && hour < 12) return "Breakfast Time";
            if (hour >= 12 && hour < 17) return "Lunch Time";
            if (hour >= 17 && hour < 21) return "Dinner Time";
            return "Late Night Snack";
        }


        public void removeTuioObject(TuioObject o)
        {
            Dispatcher.Invoke(() => {
                if (objectElements.ContainsKey(o.SessionID))
                {
                    MainCanvas.Children.Remove(objectElements[o.SessionID]);
                    objectElements.Remove(o.SessionID);
                }

                // Sticky menu: Don't remove ID 0 menu here
                // It stays until center dwell or app close
            });
        }
        #endregion

        #region TUIO Blobs
        public void addTuioBlob(TuioBlob b)
        {
            Dispatcher.Invoke(() => {
                Grid container = CreateContainer(40, 30, Brushes.Gray, Brushes.White, true, b.BlobID.ToString());
                blobElements[b.SessionID] = container;
                MainCanvas.Children.Add(container);
                UpdateElementPosition(container, b.X, b.Y, b.Angle);
            });
        }

        public void updateTuioBlob(TuioBlob b)
        {
            Dispatcher.Invoke(() => {
                if (blobElements.ContainsKey(b.SessionID))
                    UpdateElementPosition(blobElements[b.SessionID], b.X, b.Y, b.Angle);
            });
        }

        public void removeTuioBlob(TuioBlob b)
        {
            Dispatcher.Invoke(() => {
                if (blobElements.ContainsKey(b.SessionID))
                {
                    MainCanvas.Children.Remove(blobElements[b.SessionID]);
                    blobElements.Remove(b.SessionID);
                }
            });
        }
        #endregion

        #region Cooking Menu
        private FrameworkElement CreateCircularMenu()
        {
            double maxRadius = 260; 
            double innerR = 60;
            double middleR = 150;
            double center = maxRadius;

            Grid menuRoot = new Grid { Width = maxRadius * 2, Height = maxRadius * 2 };
            innerSegmentList = new List<Path>();
            outerSegmentList = new List<Path>();
            
            var mainItems = new[] {
                new { Label = "Timer", Emoji = "⏱️", Color = Color.FromRgb(255, 107, 107) },       // 0: Top
                new { Label = "Recipes", Emoji = "📖", Color = Color.FromRgb(78, 205, 196) },     // 1
                new { Label = "Ingredients", Emoji = "🥕", Color = Color.FromRgb(255, 230, 109) }, // 2
                new { Label = "Heat", Emoji = "🔥", Color = Color.FromRgb(255, 159, 64) },        // 3
                new { Label = "EXIT", Emoji = "❌", Color = Color.FromRgb(255, 0, 0) },           // 4: BOTTOM
                new { Label = "Tutorials", Emoji = "🎥", Color = Color.FromRgb(162, 155, 254) },  // 5
                new { Label = "Shopping", Emoji = "🛒", Color = Color.FromRgb(85, 239, 196) },    // 6
                new { Label = "Scales", Emoji = "⚖️", Color = Color.FromRgb(129, 236, 236) }      // 7
            };

            // 1. Build Inner Ring
            double angleStep = 360.0 / mainItems.Length;
            for (int i = 0; i < mainItems.Length; i++)
            {
                Path seg = CreatePieSegment(center, center, innerR, middleR, i * angleStep, (i + 1) * angleStep);
                seg.Tag = mainItems[i].Label;
                Color baseColor = mainItems[i].Color;
                seg.Fill = new LinearGradientBrush(Color.FromArgb(160, baseColor.R, baseColor.G, baseColor.B), Color.FromArgb(20, baseColor.R, baseColor.G, baseColor.B), 45);
                seg.Stroke = Brushes.White;
                seg.StrokeThickness = 1;
                
                innerSegmentList.Add(seg);
                menuRoot.Children.Add(seg);

                // Add Labels
                double midRad = ((i * angleStep + (i + 1) * angleStep) / 2.0 - 90) * (Math.PI / 180.0);
                double lx = center + Math.Cos(midRad) * (innerR + middleR) / 2.0;
                double ly = center + Math.Sin(midRad) * (innerR + middleR) / 2.0;
                
                StackPanel sp = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
                sp.Children.Add(new TextBlock { Text = mainItems[i].Emoji, FontSize = 20, HorizontalAlignment = HorizontalAlignment.Center });
                sp.Children.Add(new TextBlock { Text = mainItems[i].Label, Foreground = Brushes.White, FontSize = 9, FontWeight = FontWeights.Bold, HorizontalAlignment = HorizontalAlignment.Center });
                
                Canvas cv = new Canvas();
                Grid g = new Grid { Width = 60, Height = 40 }; g.Children.Add(sp);
                Canvas.SetLeft(g, lx - 30); Canvas.SetTop(g, ly - 20);
                cv.Children.Add(g);
                menuRoot.Children.Add(cv);
            }

            return menuRoot;
        }

        private void ShowOuterRing(string type)
        {
            if (cookingMenu == null || activeSubMenu == type) return;
            
            // Clean previous outer ring
            Grid menu = cookingMenu as Grid;
            var toRemove = new List<UIElement>();
            foreach (UIElement child in menu.Children) if (child is Path p && outerSegmentList.Contains(p)) toRemove.Add(child);
            foreach (UIElement child in menu.Children) if (child is Canvas cv && cv.Tag?.ToString() == "OuterLabel") toRemove.Add(child);
            foreach (var r in toRemove) menu.Children.Remove(r);
            outerSegmentList.Clear();

            activeSubMenu = type;
            if (type == "None") return;

            double center = menu.Width / 2;
            double innerR = 160;
            double outerR = 250;

            string[] labels; string[] emojis; Color ringColor;
            if (type == "Timer") {
                labels = new[] { "5m", "10m", "15m", "20m", "30m", "45m", "60m", "CLOSE" };
                emojis = new[] { "⏲️", "⏲️", "⏲️", "⏲️", "⏲️", "⏲️", "⏲️", "✖️" };
                ringColor = Color.FromRgb(255, 107, 107);
            } else if (type == "Heat") {
                labels = new[] { "Low", "Med", "High", "Sear", "Warm", "CLOSE" };
                emojis = new[] { "🧊", "🌤️", "🔥", "💥", "♨️", "✖️" };
                ringColor = Color.FromRgb(255, 159, 64);
            } else {
                labels = new[] { "Salad", "Soup", "Pasta", "Steak", "CLOSE" };
                emojis = new[] { "🥗", "🍲", "🍝", "🥩", "✖️" };
                ringColor = Color.FromRgb(78, 205, 196);
            }

            double step = 360.0 / labels.Length;
            for (int i = 0; i < labels.Length; i++)
            {
                Path seg = CreatePieSegment(center, center, innerR, outerR, i * step, (i + 1) * step);
                seg.Tag = labels[i];
                seg.Fill = new SolidColorBrush(Color.FromArgb(140, ringColor.R, ringColor.G, ringColor.B));
                seg.Stroke = Brushes.White;
                seg.StrokeThickness = 0.5;
                
                menu.Children.Add(seg);
                outerSegmentList.Add(seg);

                double midRad = ((i * step + (i + 1) * step) / 2.0 - 90) * (Math.PI / 180.0);
                double lx = center + Math.Cos(midRad) * (innerR + outerR) / 2.0;
                double ly = center + Math.Sin(midRad) * (innerR + outerR) / 2.0;
                
                TextBlock txt = new TextBlock { Text = emojis[i] + " " + labels[i], Foreground = Brushes.White, FontSize = 10, FontWeight = FontWeights.Bold };
                Canvas cv = new Canvas { Tag = "OuterLabel" };
                Canvas.SetLeft(txt, lx - 20); Canvas.SetTop(txt, ly - 10);
                cv.Children.Add(txt);
                menu.Children.Add(cv);
            }
        }

        private void CheckMenuSelection(float cursorX, float cursorY)
        {
            if (cookingMenu == null) return;

            FrameworkElement menu = cookingMenu;
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;

            double menuCenterX = Canvas.GetLeft(menu) + (menu.Width / 2);
            double menuCenterY = Canvas.GetTop(menu) + (menu.Height / 2);
            double dx = (cursorX * canvasW) - menuCenterX;
            double dy = (cursorY * canvasH) - menuCenterY;
            double dist = Math.Sqrt(dx * dx + dy * dy);
            double angle = (Math.Atan2(dy, dx) * 180.0 / Math.PI) + 90;
            if (angle < 0) angle += 360;

            if (dist > 60 && dist < 150) // Inner Ring
            {
                int idx = (int)(angle / (360.0 / 8)) % 8;
                HandleHoverDwell("Inner", idx);
            }
            else if (dist > 160 && dist < 250) // Outer Ring
            {
                if (outerSegmentList.Count == 0) { ClearAllHover(); return; }
                int idx = (int)(angle / (360.0 / outerSegmentList.Count)) % outerSegmentList.Count;
                HandleHoverDwell("Outer", idx);
            }
            else
            {
                ClearAllHover();
            }
        }

        private void HandleHoverDwell(string ring, int index)
        {
            // 1. If we moved to a DIFFERENT segment/ring, reset everything
            if (lastHoveredRing != ring || lastHoveredSegment != index)
            {
                lastHoveredRing = ring;
                lastHoveredSegment = index;
                segmentHoverStart = DateTime.Now; // Reset dwell timer for the NEW target
                
                if (ring == "Inner") { HighlightInner(index, 0); HighlightOuter(-1, 0); }
                else { HighlightOuter(index, 0); HighlightInner(-1, 0); }
                return;
            }

            // 2. If we are still on the SAME segment, check if it's already triggered (cooldown)
            if (segmentHoverStart > DateTime.Now)
            {
                if (ring == "Inner") HighlightInner(index, 1.0);
                else HighlightOuter(index, 1.0);
                return;
            }

            // 3. Normal Dwell Logic
            double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
            double progress = Math.Max(0, Math.Min(1.0, elapsed / 1.0)); // 1s dwell
            
            if (ring == "Inner") HighlightInner(index, progress);
            else HighlightOuter(index, progress);

            if (elapsed >= 1.0)
            {
                if (ring == "Inner") HandleInnerSelection(index);
                else HandleOuterSelection(index);
                segmentHoverStart = DateTime.Now.AddDays(1); // Selection cooldown for THIS segment
            }
        }

        private void HandleInnerSelection(int index)
        {
            string label = innerSegmentList[index].Tag.ToString();
            if (label == "EXIT") RemoveActiveMenu();
            else if (label == "Timer" || label == "Heat" || label == "Recipes") ShowOuterRing(label);
        }

        private void HandleOuterSelection(int index)
        {
            var list = outerSegmentList;
            string label = list[index].Tag.ToString();

            if (label.Contains("m")) // Timer
            {
                int mins = int.Parse(label.Replace("m", ""));
                StartKitchenTimer(mins);
            }
            else if (label == "CLOSE") ShowOuterRing("None");
            else {
                // For Heat or Recipes
                ContextDisplay.Text = $"Context: Selected {label}";
            }
        }

        private void HighlightOuter(int index, double progress)
        {
            var segments = outerSegmentList;
            for (int i = 0; i < segments.Count; i++)
            {
                if (i == index) {
                    double p = Math.Max(0, Math.Min(1.0, progress));
                    segments[i].Stroke = p >= 1.0 ? Brushes.Lime : Brushes.Gold;
                    segments[i].StrokeThickness = 1 + (5 * p);
                    segments[i].Opacity = 1.0;
                } else {
                    segments[i].Stroke = Brushes.White;
                    segments[i].StrokeThickness = 0.5;
                    segments[i].Opacity = 0.4;
                }
            }
        }

        private void HighlightInner(int index, double progress)
        {
            var segments = innerSegmentList;
            for (int i = 0; i < segments.Count; i++)
            {
                if (i == index) {
                    double p = Math.Max(0, Math.Min(1.0, progress));
                    segments[i].Stroke = p >= 1.0 ? Brushes.Lime : Brushes.Gold;
                    segments[i].StrokeThickness = 2 + (6 * p);
                    segments[i].Opacity = 1.0;
                } else {
                    segments[i].Stroke = Brushes.White;
                    segments[i].StrokeThickness = 1;
                    segments[i].Opacity = 0.4;
                }
            }
        }

        private void ClearAllHover()
        {
            if (cookingMenu == null) return;
            HighlightInner(-1, 0);
            HighlightOuter(-1, 0);
            lastHoveredSegment = -1;
            lastHoveredRing = "None";
        }

        private void RemoveActiveMenu()
        {
            if (cookingMenu != null)
            {
                MainCanvas.Children.Remove(cookingMenu);
                cookingMenu = null;
                innerSegmentList.Clear();
                outerSegmentList.Clear();
                activeMenuSessionId = -1;
                lastHoveredSegment = -1;
            }
        }

        private Path CreatePieSegment(double centerX, double centerY, double innerRadius, double outerRadius, double startAngle, double endAngle)
        {
            // Convert to radians
            double startRad = (startAngle - 90) * (Math.PI / 180.0);
            double endRad = (endAngle - 90) * (Math.PI / 180.0);

            Point p1 = new Point(centerX + Math.Cos(startRad) * outerRadius, centerY + Math.Sin(startRad) * outerRadius);
            Point p2 = new Point(centerX + Math.Cos(endRad) * outerRadius, centerY + Math.Sin(endRad) * outerRadius);
            Point p3 = new Point(centerX + Math.Cos(endRad) * innerRadius, centerY + Math.Sin(endRad) * innerRadius);
            Point p4 = new Point(centerX + Math.Cos(startRad) * innerRadius, centerY + Math.Sin(startRad) * innerRadius);

            PathFigure figure = new PathFigure { StartPoint = p1, IsClosed = true };
            figure.Segments.Add(new ArcSegment(p2, new Size(outerRadius, outerRadius), 0, false, SweepDirection.Clockwise, true));
            figure.Segments.Add(new LineSegment(p3, true));
            figure.Segments.Add(new ArcSegment(p4, new Size(innerRadius, innerRadius), 0, false, SweepDirection.Counterclockwise, true));

            PathGeometry geom = new PathGeometry();
            geom.Figures.Add(figure);

            return new Path { Data = geom };
        }
        #endregion

        #region Helpers
        private Grid CreateContainer(double w, double h, Brush fill, Brush stroke, bool isEllipse, string label)
        {
            Grid g = new Grid() { Width = w, Height = h };
            Shape shape = isEllipse ? (Shape)new Ellipse() : (Shape)new Rectangle();
            shape.Fill = fill;
            shape.Stroke = stroke;
            shape.StrokeThickness = 2;

            TextBlock txt = new TextBlock()
            {
                Text = label,
                Foreground = Brushes.White,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                FontSize = 10
            };

            g.Children.Add(shape);
            g.Children.Add(txt);
            return g;
        }

        private void UpdateElementPosition(FrameworkElement el, float normX, float normY, float angle = 0)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;

            Canvas.SetLeft(el, (normX * canvasW) - (el.Width / 2));
            Canvas.SetTop(el, (normY * canvasH) - (el.Height / 2));

            if (angle != 0)
            {
                el.RenderTransformOrigin = new Point(0.5, 0.5);
                el.RenderTransform = new RotateTransform(angle * (180.0 / Math.PI));
            }
        }

        public void refresh(TuioTime frameTime)
        {
            Dispatcher.Invoke(() => {
                ContextDisplay.Text = "Context: " + GetCurrentTimeContext();
            });
        }
        #endregion
    }
}

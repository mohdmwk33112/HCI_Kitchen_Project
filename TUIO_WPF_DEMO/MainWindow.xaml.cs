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
        private List<Border> adminDeleteButtons = new List<Border>();
        private TuioClient client;
        private TcpClient pythonClient;
        private NetworkStream stream;

        // Track UI elements by their TUIO SessionID
        private Dictionary<long, FrameworkElement> cursorElements = new Dictionary<long, FrameworkElement>();
        private Dictionary<long, FrameworkElement> objectElements = new Dictionary<long, FrameworkElement>();
        private Dictionary<long, FrameworkElement> blobElements = new Dictionary<long, FrameworkElement>();
        private StackPanel ingredientListPanel;


        
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

        // --- Camera & State Management ---
        private bool _isHomeOpen = false;
        private bool _isMenuOpen = false;
        private bool _isLogoutPopupOpen = false;
        private bool _showRecipeCard = false;
        private bool _isCooking = false; // Prevents overview card from appearing during steps
        private Ellipse cameraPointer; // Visual representation of the camera index finger
        private double lastCamX = 0, lastCamY = 0;
        private string _userSide = "Left"; // Default
        private bool _hadPositiveEmotion = false;
        private string _lastSentEmotion = "neutral";
        private DateTime _lastEmotionTime = DateTime.MinValue;
        // --- Keyboard State Management ---
        private bool _isKeyboardOpen = false;
        private Grid keyboardGrid = null;
        private TextBlock keyboardTextBox = null;
        private List<Border> keyboardKeys = new List<Border>();
        private string keyboardInputText = "";

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
                try
                {
                    var data = JsonSerializer.Deserialize<Dictionary<string, object>>(message);
                    
                    // 1. Handle Continuous Pointer Tracking
                    if (data.ContainsKey("type") && data["type"].ToString() == "pointer")
                    {
                        double x = double.Parse(data["x"].ToString());
                        double y = double.Parse(data["y"].ToString());
                        lastCamX = x; lastCamY = y;

                        UpdateCameraPointer(x, y);
                        HandlePointerInput(x, y);
                        return;
                    }

                    // 1b. Handle Emotion
                    if (data.ContainsKey("type") && data["type"].ToString() == "emotion")
                    {
                        string emotion = data["value"].ToString();
                        
                        // TRACK EMOTION FOR ADAPTIVE UI
                        if (emotion == "happy") _hadPositiveEmotion = true;
                        
                        // Send emotion to server if cooking and changed (throttle 1s)
                        if (_isCooking && emotion != _lastSentEmotion && (DateTime.Now - _lastEmotionTime).TotalSeconds > 1.0) {
                            SendToServer($"EMOTION;{emotion}");
                            _lastSentEmotion = emotion;
                            _lastEmotionTime = DateTime.Now;
                        }
                        return;
                    }

                    // 1b. Handle Ingredient Detections
                    if (data.ContainsKey("type") && data["type"].ToString() == "detections")
                    {
                        var ingredients = (JsonElement)data["ingredients"];
                        Dispatcher.Invoke(() => UpdateIngredientDetections(ingredients));
                        return;
                    }


                    // 2. Handle Discrete Gestures (Only if menu is closed)
                    if (data.ContainsKey("gesture"))
                    {
                        if (_isMenuOpen) return; // Suppress camera gestures while menu is open

                        string gesture = data["gesture"].ToString();
                        double confidence = double.Parse(data["confidence"].ToString());
                        
                        double normX = lastCamX; // Use last known pointer pos for context
                        double normY = lastCamY;
                        if (data.ContainsKey("x") && data.ContainsKey("y"))
                        {
                            normX = double.Parse(data["x"].ToString());
                            normY = double.Parse(data["y"].ToString());
                        }

                        Dispatcher.Invoke(() => {
                            ContextDisplay.Text = $"Context: Gesture -> {gesture} ({confidence})";
                            if (gesture == "Swipe Left") { SendToServer("PREV"); }
                            else if (gesture == "Swipe Right") { SendToServer("NEXT"); }
                            else if (gesture == "Click") { HandlePointerInput(normX, normY); }
                            else if (gesture == "Circle") { OpenCircularMenu(normX, normY); }
                            else if (gesture == "L Shape") { OpenLogoutPopup(); }
                        });
                    }
                }
                catch (Exception ex) { System.Diagnostics.Debug.WriteLine("JSON Error: " + ex.Message); }
            }
            else if (message.StartsWith("login_success"))
            {
                string[] parts = message.Split(';');
                string userName = parts.Length > 1 ? parts[1] : "Unknown";
                string side = parts.Length > 2 ? parts[2] : "Left";
                
                _userSide = side;
                ShiftContent(side);
                TimerDashboard.Visibility = Visibility.Visible;
                HomePanel.Visibility = Visibility.Visible;
                _isHomeOpen = true;
                
                ContextDisplay.Text = $"Welcome, {userName}";
                
                // ADMIN ROLE SEPARATION:
                if (userName.ToLower() == "wael") {
                    AdminChoicePanel.Visibility = Visibility.Visible;
                    HomePanel.Visibility = Visibility.Collapsed;
                    ContextDisplay.Text = "Administrator Access";
                } else {
                    HomePanel.Visibility = Visibility.Visible;
                    AdminChoicePanel.Visibility = Visibility.Collapsed;
                    SendToServer("GET_SUGGESTION");
                }
            }
            else if (message.StartsWith("suggestion"))
            {
                string[] parts = message.Split(';');
                if (parts.Length > 2) {
                    string suggName = parts[2];
                    ContextDisplay.Text = $"Context: I suggest making {suggName}. Scan TUIO to begin!";
                }
            }
            else if (message.StartsWith("login_failed"))
            {
                ContextDisplay.Text = "Context: Face Login Failed. " + message;
                KeyboardPopUp();
            }
            else if (message.StartsWith("step"))
            {
                // Hide panels when steps start
                RecipePanel.Visibility = Visibility.Collapsed;
                HomePanel.Visibility = Visibility.Collapsed;
                StepPanel.Visibility = Visibility.Visible;
                _isCooking = true;
                _isHomeOpen = false;

                // Format: step;index;total;instruction
                string[] parts = message.Split(';');
                if (parts.Length >= 4)
                {
                    int current = int.Parse(parts[1]);
                    int total = int.Parse(parts[2]);

                    StepNumberText.Text = $"STEP {current} OF {total}";
                    StepInstructionText.Text = parts[3];
                    ContextDisplay.Text = "Context: Cooking in progress...";

                    // Update navigation hints
                    PrevStepHint.Visibility = current > 1 ? Visibility.Visible : Visibility.Hidden;
                    NextStepHint.Text = (current == total) ? "🏁 Swipe Right to Finish" : "Swipe Right for Next ➡️";
                }
            }
            else if (message == "session_done")
            {
                StepPanel.Visibility = Visibility.Collapsed;
                _isCooking = false;

                if (_hadPositiveEmotion) {
                    RatingPanel.Visibility = Visibility.Visible;
                    ContextDisplay.Text = "Great job!";
                } else {
                    DessertInquiryPanel.Visibility = Visibility.Visible;
                    ContextDisplay.Text = "Finished!";
                }
            }
            else if (message.StartsWith("logout_success"))
            {
                string[] parts = message.Split(';');
                string side = parts.Length > 1 ? parts[1] : "Center";

                _isLogoutPopupOpen = false;
                LogoutOverlay.Visibility = Visibility.Collapsed;
                HomePanel.Visibility = Visibility.Collapsed;
                RecipePanel.Visibility = Visibility.Collapsed;
                StepPanel.Visibility = Visibility.Collapsed;
                _isHomeOpen = false;
                _isCooking = false;
                
                if (ingredientListPanel != null) ingredientListPanel.Children.Clear();
                
                // Return to initial centered state
                _userSide = "Center";
                ShiftContent("Center");
                TimerDashboard.Visibility = Visibility.Collapsed;
                if (cameraPointer != null) cameraPointer.Visibility = Visibility.Collapsed;

                ContextDisplay.Text = "Please Log In";
            }
            else if (message.StartsWith("error"))
            {
                ContextDisplay.Text = "Context: Server Error - " + message;
            }
            else if (message.StartsWith("capture_success"))
            {
                string[] parts = message.Split(';');
                string name = parts.Length > 1 ? parts[1] : "User";
                ContextDisplay.Text = $"Success! {name} registered.";
                SendToServer("LIST_USERS"); // Refresh list
            }
            else if (message.StartsWith("users_list"))
            {
                string[] parts = message.Split(';');
                AdminUserListPanel.Children.Clear();
                adminDeleteButtons.Clear();
                for (int i = 1; i < parts.Length; i++) {
                    if (!string.IsNullOrEmpty(parts[i])) {
                        AddUserToAdminList(parts[i]);
                    }
                }
            }
            else if (message.StartsWith("delete_success"))
            {
                ContextDisplay.Text = "User deleted successfully.";
                SendToServer("LIST_USERS"); // Refresh list
            }
            else if (message.Contains(";") && !message.StartsWith("gestures_"))
            {
                // Handle recipe header (title;scenario;ingredients...)
                string[] parts = message.Split(';');
                string title = parts[0];
                string overview = parts[1];
                
                // Populate the new RecipePanel
                RecipeTitleText.Text = title.ToUpper();
                RecipeOverviewText.Text = overview;
                
                StringBuilder sb = new StringBuilder();
                for (int i = 2; i < parts.Length; i += 3) {
                    if (i + 2 < parts.Length)
                        sb.AppendLine($"• {parts[i]} ({parts[i+1]} {parts[i+2]})");
                }
                RecipeIngredientsText.Text = sb.ToString();
                
                // ONLY show the panel if it was triggered by a TUIO scan AND not currently cooking
                if (_showRecipeCard && !_isCooking && AdminChoicePanel.Visibility != Visibility.Visible) {
                    HomePanel.Visibility = Visibility.Collapsed;
                    AdminChoicePanel.Visibility = Visibility.Collapsed;
                    _isHomeOpen = false;
                    RecipePanel.Visibility = Visibility.Visible;
                    ContextDisplay.Text = "Recipe Details"; 
                    _showRecipeCard = false; // Reset flag only after successful display
                } else if (!_isCooking) {
                    ContextDisplay.Text = $"Ready to cook {title}.";
                }
                
                SendToServer("START_GESTURES");
            }
        }

        private void UpdateCameraPointer(double normX, double normY)
        {
            if (cameraPointer == null)
            {
                cameraPointer = new Ellipse { 
                    Width = 40, Height = 40, 
                    Stroke = Brushes.Cyan, StrokeThickness = 3,
                    Fill = new SolidColorBrush(Color.FromArgb(100, 0, 255, 255)),
                    IsHitTestVisible = false
                };
                MainCanvas.Children.Add(cameraPointer);
            }
            cameraPointer.Visibility = Visibility.Visible;
            UpdateElementPosition(cameraPointer, (float)normX, (float)normY);
        }

        private void UpdateIngredientDetections(JsonElement ingredients)
        {
            // Initialize the panel if it doesn't exist
            if (ingredientListPanel == null)
            {
                ingredientListPanel = new StackPanel {
                    Orientation = Orientation.Vertical,
                    IsHitTestVisible = false
                };
                MainCanvas.Children.Add(ingredientListPanel);
                // Initial positioning based on user side
                UpdateIngredientPanelPosition();
            }

            ingredientListPanel.Children.Clear();

            // Use a HashSet to avoid duplicates in the list
            var uniqueIngredients = new HashSet<string>();
            foreach (var item in ingredients.EnumerateArray())
            {
                uniqueIngredients.Add(item.GetProperty("label").GetString());
            }

            if (uniqueIngredients.Count > 0)
            {
                ingredientListPanel.Children.Add(new TextBlock {
                    Text = "INGREDIENTS",
                    Foreground = Brushes.Yellow,
                    FontSize = 14,
                    FontWeight = FontWeights.Bold,
                    Opacity = 0.7,
                    Margin = new Thickness(0, 0, 0, 8)
                });

                foreach (var label in uniqueIngredients)
                {
                    ingredientListPanel.Children.Add(new TextBlock {
                        Text = "• " + label.ToUpper(),
                        Foreground = Brushes.White,
                        FontSize = 24,
                        FontWeight = FontWeights.Bold,
                        Effect = new System.Windows.Media.Effects.DropShadowEffect { BlurRadius = 5, ShadowDepth = 2 },
                        Margin = new Thickness(0, 0, 0, 4)
                    });
                }
            }
        }

        private void ShiftContent(string side)
        {
            if (side == "Right")
            {
                ContextDisplay.HorizontalAlignment = HorizontalAlignment.Right;
                TimerDashboard.HorizontalAlignment = HorizontalAlignment.Right;
            }
            else if (side == "Left")
            {
                ContextDisplay.HorizontalAlignment = HorizontalAlignment.Left;
                TimerDashboard.HorizontalAlignment = HorizontalAlignment.Left;
            }
            else // Center
            {
                ContextDisplay.HorizontalAlignment = HorizontalAlignment.Center;
                TimerDashboard.HorizontalAlignment = HorizontalAlignment.Center;
            }

            UpdateIngredientPanelPosition();
        }

        private void UpdateIngredientPanelPosition()
        {
            if (ingredientListPanel == null) return;

            Canvas.SetTop(ingredientListPanel, 100);
            if (_userSide == "Right")
            {
                Canvas.SetLeft(ingredientListPanel, double.NaN);
                Canvas.SetRight(ingredientListPanel, 30);
            }
            else if (_userSide == "Left")
            {
                Canvas.SetRight(ingredientListPanel, double.NaN);
                Canvas.SetLeft(ingredientListPanel, 30);
            }
            else // Center
            {
                Canvas.SetRight(ingredientListPanel, double.NaN);
                Canvas.SetLeft(ingredientListPanel, (MainCanvas.ActualWidth / 2) - 100);
            }
        }



        private void OpenCircularMenu(double x, double y)
        {
            if (_isMenuOpen) return;
            _isMenuOpen = true;
            SendToServer("MENU_OPEN");
            cookingMenu = CreateCircularMenu();
            MainCanvas.Children.Add(cookingMenu);
            UpdateElementPosition(cookingMenu, (float)x, (float)y);
            
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            menuFixedCenter = new Point(x * canvasW, y * canvasH);
            
            // Highlight existing cursors
            foreach(var el in cursorElements.Values) {
                if (el is Grid g && g.Children[0] is Shape s) {
                    s.Stroke = Brushes.Gold;
                    s.StrokeThickness = 4;
                }
            }
        }

        private void CloseCircularMenu()
        {
            if (!_isMenuOpen) return;
            _isMenuOpen = false;
            SendToServer("MENU_CLOSED");
            RemoveActiveMenu();
            
            // Reset cursors
            foreach(var el in cursorElements.Values) {
                if (el is Grid g && g.Children[0] is Shape s) {
                    s.Stroke = Brushes.Blue;
                    s.StrokeThickness = 2;
                }
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
                // If menu is open, TUIO cursors become selection pointers
                Brush fill = _isMenuOpen ? Brushes.White : new SolidColorBrush(Color.FromRgb(52, 152, 219));
                Brush stroke = _isMenuOpen ? new SolidColorBrush(Color.FromRgb(241, 196, 15)) : Brushes.White;
                
                Grid container = CreateContainer(25, 25, fill, stroke, true, "");
                cursorElements[c.SessionID] = container;
                MainCanvas.Children.Add(container);
                UpdateElementPosition(container, c.X, c.Y);
                HandlePointerInput(c.X, c.Y);
            });
        }

        public void updateTuioCursor(TuioCursor c)
        {
            Dispatcher.Invoke(() => {
                if (cursorElements.ContainsKey(c.SessionID))
                {
                    UpdateElementPosition(cursorElements[c.SessionID], c.X, c.Y);
                    HandlePointerInput(c.X, c.Y);
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
                Grid container = CreateContainer(50, 50, new SolidColorBrush(Color.FromRgb(44, 62, 80)), Brushes.White, false, o.SymbolID.ToString());
                objectElements[o.SessionID] = container;
                MainCanvas.Children.Add(container);
                UpdateElementPosition(container, o.X, o.Y, o.Angle);

                // ID 10 opens the circular menu (unused id)
                if (o.SymbolID == 10) {
                    OpenCircularMenu(o.X, o.Y);
                    return;
                }

                // PREVENTION: Don't let TUIO objects interrupt an open recipe view or cooking session
                if (RecipePanel.Visibility == Visibility.Visible || _isCooking) {
                    System.Diagnostics.Debug.WriteLine($"Ignored TUIO {o.SymbolID} because a recipe is already open.");
                    return;
                }

                // Set flag to show the full card since this is a physical scan
                _showRecipeCard = true;

                // Map TUIO SymbolID to Recipe ID (0->1, 1->2, etc.)
                int recipeId = o.SymbolID + 1;
                SendToServer($"RECIPE_ID;{recipeId}");
                
                System.Diagnostics.Debug.WriteLine($"TUIO {o.SymbolID} scanned. Requesting Recipe {recipeId}");
            });
        }

        public void updateTuioObject(TuioObject o)
        {
            Dispatcher.Invoke(() => {
                if (objectElements.ContainsKey(o.SessionID))
                {
                    UpdateElementPosition(objectElements[o.SessionID], o.X, o.Y, o.Angle);

                    // NAVIGATION: If already cooking, use rotation for steps
                    if (_isCooking && StepPanel.Visibility == Visibility.Visible) {
                        if (o.RotationSpeed > 2.5f) { // Fast flick Right
                             SendToServer("NEXT");
                             System.Diagnostics.Debug.WriteLine("Next Step via TUIO Rotation");
                        } else if (o.RotationSpeed < -2.5f) { // Fast flick Left
                             SendToServer("PREV");
                             System.Diagnostics.Debug.WriteLine("Prev Step via TUIO Rotation");
                        }
                    }
                    // If user rotates RIGHT, confirm recipe and start steps
                    else if (o.RotationSpeed > 1.8f && !_isCooking && RecipePanel.Visibility == Visibility.Visible) {
                         SendToServer("CONFIRM");
                         _isCooking = true;
                         System.Diagnostics.Debug.WriteLine("Recipe Confirmed via TUIO Rotation");
                    }
                    // If user rotates LEFT, cancel recipe selection
                    else if (o.RotationSpeed < -1.8f && !_isCooking && RecipePanel.Visibility == Visibility.Visible) {
                        CancelRecipe();
                        System.Diagnostics.Debug.WriteLine("Recipe Cancelled via TUIO Rotation");
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
                if (o.SymbolID == 10) CloseCircularMenu();

                if (objectElements.ContainsKey(o.SessionID))
                {
                    MainCanvas.Children.Remove(objectElements[o.SessionID]);
                    objectElements.Remove(o.SessionID);
                }
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
                seg.Fill = new SolidColorBrush(Color.FromArgb(200, baseColor.R, baseColor.G, baseColor.B));
                seg.Stroke = Brushes.White;
                seg.StrokeThickness = 2;
                
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
                seg.Fill = new SolidColorBrush(Color.FromArgb(220, ringColor.R, ringColor.G, ringColor.B));
                seg.Stroke = Brushes.White;
                seg.StrokeThickness = 2;
                
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
            if (label == "EXIT") CloseCircularMenu();
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

        #region Logout Popup
        private void HandlePointerInput(double x, double y)
        {
            if (_isLogoutPopupOpen)
            {
                CheckPopupSelection((float)x, (float)y);
            }
            else if (_isMenuOpen)
            {
                CheckMenuSelection((float)x, (float)y);
            }
            else if (RecipePanel.Visibility == Visibility.Visible)
            {
                CheckRecipeDetailSelection((float)x, (float)y);
            }
            else if (AdminChoicePanel.Visibility == Visibility.Visible)
            {
                CheckAdminChoiceSelection((float)x, (float)y);
            }
            else if (AdminPanel.Visibility == Visibility.Visible)
            {
                CheckAdminSelection((float)x, (float)y);
            }
            else if (StepPanel.Visibility == Visibility.Visible)
            {
                CheckStepPanelSelection((float)x, (float)y);
            }
            else if (RatingPanel.Visibility == Visibility.Visible)
            {
                CheckRatingSelection((float)x, (float)y);
            }
            else if (DessertInquiryPanel.Visibility == Visibility.Visible)
            {
                CheckDessertInquirySelection((float)x, (float)y);
            }
            else if (HomePanel.Visibility == Visibility.Visible)
            {
                CheckHomeSelection((float)x, (float)y);
            }
            if (_isKeyboardOpen)
            {
                CheckKeyboardSelection((float)x, (float)y);
            }
        }

        private void CheckRecipeDetailSelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            if (IsPointInElement(p, BtnStartCooking))
            {
                if (lastHoveredRing != "Detail" || lastHoveredSegment != 1)
                {
                    lastHoveredRing = "Detail";
                    lastHoveredSegment = 1;
                    segmentHoverStart = DateTime.Now;
                    return;
                }

                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                double prg = Math.Max(0, Math.Min(1.0, elapsed / 1.5));
                StartCookingBar.Width = prg * StartCookingProgress.ActualWidth;

                if (elapsed >= 1.5)
                {
                    SendToServer("CONFIRM");
                    _isCooking = true;
                    segmentHoverStart = DateTime.Now.AddDays(1);
                }
            }
            else if (IsPointInElement(p, BtnCancelRecipe))
            {
                if (lastHoveredRing != "Detail" || lastHoveredSegment != 0)
                {
                    lastHoveredRing = "Detail";
                    lastHoveredSegment = 0;
                    segmentHoverStart = DateTime.Now;
                    return;
                }

                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                double prg = Math.Max(0, Math.Min(1.0, elapsed / 1.5));
                CancelRecipeBar.Width = prg * CancelRecipeProgress.ActualWidth;

                if (elapsed >= 1.5)
                {
                    CancelRecipe();
                }
            }
            else
            {
                StartCookingBar.Width = 0;
                CancelRecipeBar.Width = 0;
                lastHoveredSegment = -1;
            }
        }

        private void CancelRecipe()
        {
            // Collapse all cooking-related panels
            RecipePanel.Visibility = Visibility.Collapsed;
            StepPanel.Visibility = Visibility.Collapsed;
            RatingPanel.Visibility = Visibility.Collapsed;
            DessertInquiryPanel.Visibility = Visibility.Collapsed;
            TimerDashboard.Visibility = Visibility.Collapsed;

            HomePanel.Visibility = Visibility.Visible;
            _isHomeOpen = true;
            _isCooking = false;
            _showRecipeCard = false;
            _hadPositiveEmotion = false; // Reset session emotion
            
            ContextDisplay.Text = "Recipe Interrupted. Choose another.";
            SendToServer("CANCEL");
            
            // Reset all dwelling states completely
            lastHoveredRing = "None";
            lastHoveredSegment = -1;
            segmentHoverStart = DateTime.MinValue; 
            
            // Clean bars
            if (StartCookingBar != null) StartCookingBar.Width = 0;
            if (CancelRecipeBar != null) CancelRecipeBar.Width = 0;
            if (StopCookingBar != null) StopCookingBar.Width = 0;
            
            Border[] bars = { Bar1, Bar2, Bar3, Bar4 };
            foreach (var b in bars) if (b != null) b.Width = 0;
        }

        private void CheckHomeSelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            Border[] cards = { RecipeCard1, RecipeCard2, RecipeCard3, RecipeCard4 };
            Border[] bars = { Bar1, Bar2, Bar3, Bar4 };
            Border[] progress = { Progress1, Progress2, Progress3, Progress4 };

            bool found = false;
            for (int i = 0; i < cards.Length; i++)
            {
                if (IsPointInElement(p, cards[i]))
                {
                    found = true;
                    if (lastHoveredRing != "Home" || lastHoveredSegment != i)
                    {
                        lastHoveredRing = "Home";
                        lastHoveredSegment = i;
                        segmentHoverStart = DateTime.Now;
                        return;
                    }

                    double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                    double prg = Math.Max(0, Math.Min(1.0, elapsed / 1.5));
                    bars[i].Width = prg * progress[i].ActualWidth;

                    if (elapsed >= 1.5)
                    {
                        _showRecipeCard = true;
                        int recipeId = int.Parse(cards[i].Tag.ToString());
                        SendToServer($"RECIPE_ID;{recipeId}");
                        ContextDisplay.Text = "Loading Recipe Details...";
                        
                        // Set state to Cooldown to prevent repeat sends
                        lastHoveredRing = "Cooldown";
                        segmentHoverStart = DateTime.MaxValue; 
                    }
                    return; // EXIT loop since we found the card
                }
                else
                {
                    bars[i].Width = 0;
                }
            }

            if (!found)
            {
                lastHoveredRing = "None";
                lastHoveredSegment = -1;
            }
        }

        private void CheckAdminChoiceSelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            // 1. Enter Kitchen
            if (IsPointInElement(p, BtnEnterKitchen))
            {
                if (lastHoveredRing != "Choice" || lastHoveredSegment != 1) {
                    lastHoveredRing = "Choice";
                    lastHoveredSegment = 1;
                    segmentHoverStart = DateTime.Now;
                    return;
                }
                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                EnterKitchenBar.Width = Math.Min(1.0, elapsed / 1.5) * EnterKitchenProgress.ActualWidth;
                if (elapsed >= 1.5) {
                    AdminChoicePanel.Visibility = Visibility.Collapsed;
                    HomePanel.Visibility = Visibility.Visible;
                    ContextDisplay.Text = "Kitchen Hub";
                    SendToServer("GET_SUGGESTION");
                    lastHoveredRing = "Cooldown";
                    segmentHoverStart = DateTime.MaxValue;
                }
                return;
            } else { EnterKitchenBar.Width = 0; }

            // 2. Enter Admin
            if (IsPointInElement(p, BtnEnterAdmin))
            {
                if (lastHoveredRing != "Choice" || lastHoveredSegment != 2) {
                    lastHoveredRing = "Choice";
                    lastHoveredSegment = 2;
                    segmentHoverStart = DateTime.Now;
                    return;
                }
                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                EnterAdminBar.Width = Math.Min(1.0, elapsed / 1.5) * EnterAdminProgress.ActualWidth;
                if (elapsed >= 1.5) {
                    AdminChoicePanel.Visibility = Visibility.Collapsed;
                    AdminPanel.Visibility = Visibility.Visible;
                    ContextDisplay.Text = "Admin Workspace";
                    SendToServer("LIST_USERS");
                    lastHoveredRing = "Cooldown";
                    segmentHoverStart = DateTime.MaxValue;
                }
                return;
            } else { EnterAdminBar.Width = 0; }

            if (lastHoveredRing == "Choice") lastHoveredRing = "None";
        }

        private void AddUserToAdminList(string name)
        {
            Border row = new Border { Background = Brushes.White, CornerRadius = new CornerRadius(8), Margin = new Thickness(0, 2, 0, 2), Padding = new Thickness(10) };
            Grid grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            TextBlock txtName = new TextBlock { Text = name, FontSize = 18, VerticalAlignment = VerticalAlignment.Center, Foreground = new SolidColorBrush(Color.FromRgb(44, 62, 80)) };
            Grid.SetColumn(txtName, 0);

            Border btnDel = new Border { Background = new SolidColorBrush(Color.FromRgb(231, 76, 60)), CornerRadius = new CornerRadius(5), Padding = new Thickness(10, 5, 10, 5), Tag = name };
            btnDel.Child = new TextBlock { Text = "DELETE", Foreground = Brushes.White, FontWeight = FontWeights.Bold, FontSize = 12 };
            Grid.SetColumn(btnDel, 1);

            grid.Children.Add(txtName);
            grid.Children.Add(btnDel);
            row.Child = grid;

            AdminUserListPanel.Children.Add(row);
            adminDeleteButtons.Add(btnDel);
        }

        private void CheckAdminSelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            // 1. Check Capture Button
            if (IsPointInElement(p, BtnCapture))
            {
                if (lastHoveredRing != "Admin" || lastHoveredSegment != 0)
                {
                    lastHoveredRing = "Admin";
                    lastHoveredSegment = 0;
                    segmentHoverStart = DateTime.Now;
                    return;
                }

                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                double prg = Math.Max(0, Math.Min(1.0, elapsed / 1.5));
                CaptureProgressBar.Width = prg * CaptureProgress.ActualWidth;

                if (elapsed >= 1.5)
                {
                    string name = TxtNewUserName.Text.Trim();
                    if (string.IsNullOrEmpty(name)) name = "NewUser";
                    
                    SendToServer($"CAPTURE_FACE;{name}");
                    ContextDisplay.Text = $"Capturing face for {name}...";
                    
                    lastHoveredRing = "Cooldown";
                    segmentHoverStart = DateTime.MaxValue;
                    CaptureProgressBar.Width = 0;
                }
                return;
            }
            else
            {
                CaptureProgressBar.Width = 0;
            }

            // 2. Check Delete Buttons
            for (int i = 0; i < adminDeleteButtons.Count; i++)
            {
                if (IsPointInElement(p, adminDeleteButtons[i]))
                {
                    if (lastHoveredRing != "AdminList" || lastHoveredSegment != i)
                    {
                        lastHoveredRing = "AdminList";
                        lastHoveredSegment = i;
                        segmentHoverStart = DateTime.Now;
                        return;
                    }

                    double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                    // Visual feedback for delete (maybe redder?)
                    adminDeleteButtons[i].Background = new SolidColorBrush(Color.FromRgb(192, 57, 43));

                    if (elapsed >= 1.5)
                    {
                        string name = adminDeleteButtons[i].Tag.ToString();
                        SendToServer($"DELETE_USER;{name}");
                        ContextDisplay.Text = $"Deleting user {name}...";
                        lastHoveredRing = "Cooldown";
                        segmentHoverStart = DateTime.MaxValue;
                    }
                    return;
                }
                else
                {
                    // Reset color
                    adminDeleteButtons[i].Background = new SolidColorBrush(Color.FromRgb(231, 76, 60));
                }
            }

            if (lastHoveredRing == "Admin" || lastHoveredRing == "AdminList") lastHoveredRing = "None";
        }

        private void BtnExitAdmin_Click(object sender, RoutedEventArgs e)
        {
            AdminPanel.Visibility = Visibility.Collapsed;
            AdminChoicePanel.Visibility = Visibility.Visible;
            ContextDisplay.Text = "Administrator Access";
        }

        private void OpenLogoutPopup()
        {
            if (_isLogoutPopupOpen) return;
            _isLogoutPopupOpen = true;
            SendToServer("MENU_OPEN"); // Suppress server gestures
            LogoutOverlay.Visibility = Visibility.Visible;
            segmentHoverStart = DateTime.Now;
            lastHoveredSegment = -1;
            lastHoveredRing = "Popup";
        }

        private void CloseLogoutPopup(bool isLoggingOut = false)
        {
            if (!_isLogoutPopupOpen) return;
            _isLogoutPopupOpen = false;
            if (!isLoggingOut) SendToServer("MENU_CLOSED"); // Resume server gestures only if NOT logging out
            LogoutOverlay.Visibility = Visibility.Collapsed;
            ResetButtonHighlight(BtnConfirmLogout);
            ResetButtonHighlight(BtnCancelLogout);
        }

        private void CheckPopupSelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            if (IsPointInElement(p, BtnConfirmLogout))
            {
                HandlePopupDwell("Confirm");
            }
            else if (IsPointInElement(p, BtnCancelLogout))
            {
                HandlePopupDwell("Cancel");
            }
            else
            {
                ResetButtonHighlight(BtnConfirmLogout);
                ResetButtonHighlight(BtnCancelLogout);
                lastHoveredSegment = -1;
            }
        }

        private void CheckStepPanelSelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            if (IsPointInElement(p, BtnStopCooking))
            {
                if (lastHoveredRing != "Steps" || lastHoveredSegment != 0)
                {
                    lastHoveredRing = "Steps";
                    lastHoveredSegment = 0;
                    segmentHoverStart = DateTime.Now;
                    return;
                }

                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                StopCookingBar.Width = Math.Min(1.0, elapsed / 1.5) * StopCookingProgress.ActualWidth;

                if (elapsed >= 1.5)
                {
                    CancelRecipe(); // Re-use central cleanup
                    lastHoveredRing = "Cooldown";
                    segmentHoverStart = DateTime.MaxValue;
                    StopCookingBar.Width = 0;
                }
            }
            else
            {
                StopCookingBar.Width = 0;
                if (lastHoveredRing == "Steps") lastHoveredRing = "None";
            }
        }

        private bool IsPointInElement(Point p, FrameworkElement el)
        {
            try {
                // Since MainCanvas and LogoutOverlay are siblings, we must use TransformToVisual 
                // to map the button's position into the Canvas coordinate space.
                var transform = el.TransformToVisual(MainCanvas);
                Point topLeft = transform.Transform(new Point(0, 0));
                
                return p.X >= topLeft.X && p.X <= topLeft.X + el.ActualWidth &&
                       p.Y >= topLeft.Y && p.Y <= topLeft.Y + el.ActualHeight;
            } catch { return false; }
        }

        private void HandlePopupDwell(string button)
        {
            int btnIdx = (button == "Confirm" ? 1 : 0);
            if (lastHoveredRing != "Popup" || lastHoveredSegment != btnIdx)
            {
                lastHoveredRing = "Popup";
                lastHoveredSegment = btnIdx;
                segmentHoverStart = DateTime.Now;
                return;
            }

            if (segmentHoverStart > DateTime.Now) return;

            double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
            double progress = Math.Max(0, Math.Min(1.0, elapsed / 1.5)); // 1.5s for popup safety

            Border target = button == "Confirm" ? BtnConfirmLogout : BtnCancelLogout;
            target.BorderBrush = Brushes.Gold;
            target.BorderThickness = new Thickness(2 + (progress * 8));

            if (elapsed >= 1.5)
            {
                if (button == "Confirm")
                {
                    SendToServer("LOGOUT");
                    CloseLogoutPopup(true); 
                    ResetUI();
                    ContextDisplay.Text = "Context: Logging out...";
                }
                else
                {
                    CloseLogoutPopup(false);
                }
                segmentHoverStart = DateTime.Now.AddDays(1);
            }
        }

        private void ResetButtonHighlight(Border b)
        {
            if (b != null) b.BorderThickness = new Thickness(0);
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
        private void CheckRatingSelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            Border[] stars = { Star1, Star2, Star3, Star4, Star5 };
            bool found = false;

            for (int i = 0; i < stars.Length; i++)
            {
                if (IsPointInElement(p, stars[i]))
                {
                    found = true;
                    if (lastHoveredRing != "Rating" || lastHoveredSegment != i) {
                        lastHoveredRing = "Rating";
                        lastHoveredSegment = i;
                        segmentHoverStart = DateTime.Now;
                        return;
                    }

                    double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                    RatingProgressBar.Width = Math.Min(1.0, elapsed / 1.5) * RatingProgress.ActualWidth;

                    if (elapsed >= 1.5) {
                        int rating = i + 1;
                        SendToServer($"LOG;RATING;{{\"score\":{rating}}}");
                        RatingPanel.Visibility = Visibility.Collapsed;
                        DessertInquiryPanel.Visibility = Visibility.Visible;
                        ContextDisplay.Text = $"Thank you for the {rating} star rating!";
                        lastHoveredRing = "Cooldown";
                        segmentHoverStart = DateTime.MaxValue;
                    }
                    return;
                }
            }

            if (!found) {
                RatingProgressBar.Width = 0;
                if (lastHoveredRing == "Rating") lastHoveredRing = "None";
            }
        }

        private void CheckDessertInquirySelection(float normX, float normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            // YES
            if (IsPointInElement(p, BtnSeeDessert))
            {
                if (lastHoveredRing != "Dessert" || lastHoveredSegment != 1) {
                    lastHoveredRing = "Dessert";
                    lastHoveredSegment = 1;
                    segmentHoverStart = DateTime.Now;
                    return;
                }
                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                SeeDessertBar.Width = Math.Min(1.0, elapsed / 1.5) * SeeDessertProgress.ActualWidth;
                if (elapsed >= 1.5) {
                    DessertInquiryPanel.Visibility = Visibility.Collapsed;
                    _showRecipeCard = true; // Trigger recipe display
                    SendToServer("RECIPE_ID;4"); // Suggested Cake
                    lastHoveredRing = "Cooldown";
                    segmentHoverStart = DateTime.MaxValue;
                }
                return;
            } else { SeeDessertBar.Width = 0; }

            // NO
            if (IsPointInElement(p, BtnNoDessert))
            {
                if (lastHoveredRing != "Dessert" || lastHoveredSegment != 2) {
                    lastHoveredRing = "Dessert";
                    lastHoveredSegment = 2;
                    segmentHoverStart = DateTime.Now;
                    return;
                }
                double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
                NoDessertBar.Width = Math.Min(1.0, elapsed / 1.5) * NoDessertProgress.ActualWidth;
                if (elapsed >= 1.5) {
                    CancelRecipe(); // Back to home
                    lastHoveredRing = "Cooldown";
                    segmentHoverStart = DateTime.MaxValue;
                }
                return;
            } else { NoDessertBar.Width = 0; }

            if (lastHoveredRing == "Dessert") lastHoveredRing = "None";
        }

        private void ResetUI()
        {
            AdminPanel.Visibility = Visibility.Collapsed;
            AdminChoicePanel.Visibility = Visibility.Collapsed;
            HomePanel.Visibility = Visibility.Collapsed;
            RecipePanel.Visibility = Visibility.Collapsed;
            StepPanel.Visibility = Visibility.Collapsed;
            LogoutOverlay.Visibility = Visibility.Collapsed;
            TimerDashboard.Visibility = Visibility.Collapsed;
            ContextDisplay.Text = "Please Log In";
            _isCooking = false;
            _isHomeOpen = false;
        }

        private void BtnLogout_Click(object sender, RoutedEventArgs e)
        {
            OpenLogoutPopup();
        }

        #region keyboard
        public void KeyboardPopUp()
        {
            if (_isKeyboardOpen)
            {
                // Toggle OFF: Close and clean up the keyboard
                _isKeyboardOpen = false;
                if (keyboardGrid != null)
                {
                    MainCanvas.Children.Remove(keyboardGrid);
                    keyboardGrid = null;
                }
                keyboardKeys.Clear();
                
                if (lastHoveredRing == "Keyboard")
                {
                    lastHoveredRing = "None";
                    lastHoveredSegment = -1;
                }
                ContextDisplay.Text = "Context: Keyboard Closed.";
            }
            else
            {
                // Toggle ON: Initialize and display the keyboard
                _isKeyboardOpen = true;
                keyboardInputText = ""; // Clear string buffer on open
                CreateKeyboardUI();
                ContextDisplay.Text = "Context: Keyboard Opened. Hover to type.";
            }
        }
        private void CreateKeyboardUI()
        {
            keyboardKeys.Clear();

            // 1. Create main keyboard panel container
            keyboardGrid = new Grid
            {
                Width = 720,
                Height = 320,
                Background = new SolidColorBrush(Color.FromArgb(240, 20, 20, 20)), // Translucent dark gray
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(10)
            };

            // Define 5 vertical segments (Row 0: Input View, Rows 1-4: Key grids)
            for (int i = 0; i < 5; i++)
            {
                keyboardGrid.RowDefinitions.Add(new RowDefinition { Height = i == 0 ? new GridLength(45) : new GridLength(1, GridUnitType.Star) });
            }

            // 2. Build the typed text view screen (Row 0)
            Border displayBorder = new Border
            {
                Background = Brushes.Black,
                CornerRadius = new CornerRadius(5),
                Margin = new Thickness(2),
                Padding = new Thickness(12, 0, 12, 0)
            };
            keyboardTextBox = new TextBlock
            {
                Text = "Gaze to type...",
                Foreground = Brushes.Lime, // Classic terminal Green style
                FontSize = 20,
                FontWeight = FontWeights.Bold,
                VerticalAlignment = VerticalAlignment.Center
            };
            displayBorder.Child = keyboardTextBox;
            Grid.SetRow(displayBorder, 0);
            keyboardGrid.Children.Add(displayBorder);

            // 3. Define standard alphanumeric layout rows
            string[][] layout = new string[][]
            {
                new string[] { "1", "2", "3", "4", "5", "6", "7", "8", "9", "0" },
                new string[] { "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P" },
                new string[] { "A", "S", "D", "F", "G", "H", "J", "K", "L", "BACK" },
                new string[] { "Z", "X", "C", "V", "B", "N", "M", "SPACE", "CLEAR", "DONE" }
            };

            // 4. Generate keys and place inside inner row grids
            for (int r = 0; r < layout.Length; r++)
            {
                Grid rowGrid = new Grid();
                string[] rowKeys = layout[r];
                
                for (int c = 0; c < rowKeys.Length; c++)
                {
                    rowGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                    
                    Border keyBorder = new Border
                    {
                        Background = new SolidColorBrush(Color.FromRgb(55, 55, 55)),
                        BorderBrush = Brushes.Gray,
                        BorderThickness = new Thickness(1),
                        CornerRadius = new CornerRadius(6),
                        Margin = new Thickness(3)
                    };

                    // Differentiate function control buttons with unique colors
                    if (rowKeys[c] == "DONE") keyBorder.Background = new SolidColorBrush(Color.FromRgb(34, 112, 63)); // Soft green
                    else if (rowKeys[c] == "BACK" || rowKeys[c] == "CLEAR") keyBorder.Background = new SolidColorBrush(Color.FromRgb(138, 43, 43)); // Soft red
                    else if (rowKeys[c] == "SPACE") keyBorder.Background = new SolidColorBrush(Color.FromRgb(46, 76, 130)); // Soft blue

                    TextBlock keyText = new TextBlock
                    {
                        Text = rowKeys[c],
                        Foreground = Brushes.White,
                        FontSize = 15,
                        FontWeight = FontWeights.Bold,
                        HorizontalAlignment = HorizontalAlignment.Center,
                        VerticalAlignment = VerticalAlignment.Center
                    };

                    keyBorder.Child = keyText;
                    Grid.SetColumn(keyBorder, c);
                    rowGrid.Children.Add(keyBorder);
                    
                    // Append key border element to list for tracking hit detection
                    keyboardKeys.Add(keyBorder);
                }

                Grid.SetRow(rowGrid, r + 1);
                keyboardGrid.Children.Add(rowGrid);
            }

            // 5. Append keyboard to canvas and layout explicitly in dead center
            MainCanvas.Children.Add(keyboardGrid);
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Canvas.SetLeft(keyboardGrid, (canvasW - 720) / 2);
            Canvas.SetTop(keyboardGrid, (canvasH - 320) / 2);
        }
        private void CheckKeyboardSelection(double normX, double normY)
        {
            double canvasW = MainCanvas.ActualWidth > 0 ? MainCanvas.ActualWidth : this.Width;
            double canvasH = MainCanvas.ActualHeight > 0 ? MainCanvas.ActualHeight : this.Height;
            Point p = new Point(normX * canvasW, normY * canvasH);

            int hoveredIndex = -1;
            for (int i = 0; i < keyboardKeys.Count; i++)
            {
                if (IsPointInElement(p, keyboardKeys[i]))
                {
                    hoveredIndex = i;
                    break;
                }
            }

            if (hoveredIndex != -1)
            {
                HandleKeyboardDwell(hoveredIndex);
            }
            else
            {
                ResetAllKeyboardHighlights();
                lastHoveredSegment = -1;
                lastHoveredRing = "None";
            }
        }

        private void HandleKeyboardDwell(int index)
        {
            double dwellTime = 1.0; // 1.0 Second dwell time requirement to execute a click

            if (lastHoveredRing != "Keyboard" || lastHoveredSegment != index)
            {
                ResetAllKeyboardHighlights();
                lastHoveredRing = "Keyboard";
                lastHoveredSegment = index;
                segmentHoverStart = DateTime.Now;
                return;
            }

            // Handle immediate key selection input cooldown block
            if (segmentHoverStart > DateTime.Now) return; 

            double elapsed = (DateTime.Now - segmentHoverStart).TotalSeconds;
            double progress = Math.Max(0, Math.Min(1.0, elapsed / dwellTime));

            Border target = keyboardKeys[index];
            target.BorderBrush = Brushes.Gold;
            target.BorderThickness = new Thickness(1 + (progress * 6)); // Thickness blooms out visually as dwell charges up

            if (elapsed >= dwellTime)
            {
                string keyText = (target.Child as TextBlock)?.Text;
                HandleKeyboardKeyPress(keyText);

                // Put key on selection lock cooldown for 1.2s so it doesn't infinitely spam the letter
                segmentHoverStart = DateTime.Now.AddSeconds(1.2); 
                
                // Immediate selection color feedback
                target.BorderBrush = Brushes.Lime;
                target.BorderThickness = new Thickness(4);
            }
        }

        private void ResetAllKeyboardHighlights()
        {
            foreach (var key in keyboardKeys)
            {
                key.BorderBrush = Brushes.Gray;
                key.BorderThickness = new Thickness(1);
            }
        }

        #endregion
    }
}

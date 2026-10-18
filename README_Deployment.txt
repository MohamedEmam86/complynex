COMPLYNEX CMS - OFFLINE DEPLOYMENT GUIDE
========================================

Follow these instructions to quickly run ComplyNex CMS on any new Windows laptop.

PREREQUISITES
-------------
1. Python 3.9 or higher MUST be installed. 
   - Download from: https://www.python.org/downloads/
   - CRITICAL: During installation, you MUST check the box "Add Python to PATH" at the bottom of the installer window.
   
2. (Optional) Elasticsearch 9.3.0
   - If installed and running locally, screening will execute in ~2 seconds.
   - If NOT installed, the application will still work flawlessly, but screening will gracefully fall back to SQLite locally (which takes about 10 seconds).

HOW TO RUN THE APPLICATION
--------------------------
1. Extract the `ComplyNex_Offline_Version.zip` file to a folder (e.g., your Desktop).
2. Open the extracted folder so you see the files inside.
3. Double-click the `start_complynex.bat` file.
   - The first time you run this, it will automatically download and install all the necessary Machine Learning models and libraries (PyTorch, Faiss, etc.). This may take 5 to 10 minutes depending on your internet connection.
   - On subsequent runs, it will boot instantly.
4. Once the terminal says "Engine ready" and shows "Running on http://0.0.0.0:5000/", open your web browser.
5. Go to: http://localhost:5000

TROUBLESHOOTING
---------------
- If the black window flashes and closes instantly, ensure Python is added to your system environment variables (PATH).
- If you get "No module named" errors, simply delete the generated `venv_deploy` folder and double-click `start_complynex.bat` again to trigger a fresh download.

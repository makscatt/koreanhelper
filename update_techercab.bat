@echo off
setlocal EnableDelayedExpansion

:: UPDATE.bat -- copies files from Downloads into techercab 2.0 project, then DELETES them
:: Also cleans up duplicates like "app (1).py", "bot (2).py" etc.
:: Put this file in techercab 2.0 root (next to app.py)

set "DL=%USERPROFILE%\Downloads"
set "PROJECT=%~dp0"
set COUNT=0
set CLEANED=0

echo.
echo  ========================================
echo     TECHERCAB 2.0 -- FILE UPDATER
echo  ========================================
echo.
echo  Downloads: %DL%
echo  Project:   %PROJECT%
echo.

if not exist "%PROJECT%app.py" (
    echo  [ERROR] app.py not found in project root!
    echo  Put this .bat next to app.py
    echo.
    pause
    exit /b
)

if not exist "%DL%" (
    echo  [ERROR] Downloads folder not found: %DL%
    echo.
    pause
    exit /b
)

:: --- Copy files and delete from Downloads ---

:: Root -- Python
call :COPY "app.py"             "."
call :COPY "bot.py"             "."
call :COPY "analyze_project.py" "."
call :COPY "requirements.txt"   "."
call :COPY "README.md"          "."

:: Static -- CSS
call :COPY "style.css"           "static\css"
call :COPY "trainer_base.css"    "static\css"
call :COPY "pictures_retell.css" "static\css"

:: Static -- JS
call :COPY "trainer_base.js"     "static\js"
call :COPY "grammar_highlight.js" "static\js"

:: Static -- Data (JSON)
call :COPY "cards.json"          "static\data"
call :COPY "grammar.json"        "static\data"
call :COPY "lesson_1.json"       "static\data"
call :COPY "phrases.json"        "static\data"
call :COPY "pictures.json"       "static\data"
call :COPY "sentences.json"      "static\data"
call :COPY "texts.json"          "static\data"
call :COPY "verbs.json"          "static\data"
call :COPY "words-data.json"     "static\data"

:: Templates
call :COPY "base.html"               "templates"
call :COPY "dashboard.html"          "templates"
call :COPY "history.html"            "templates"
call :COPY "login.html"              "templates"
call :COPY "register.html"           "templates"
call :COPY "select_student.html"     "templates"
call :COPY "trainer_alphabet.html"   "templates"
call :COPY "trainer_base.html"       "templates"
call :COPY "trainer_cards.html"      "templates"
call :COPY "trainer_colors.html"     "templates"
call :COPY "trainer_dates.html"      "templates"
call :COPY "trainer_grammar.html"    "templates"
call :COPY "trainer_hub.html"        "templates"
call :COPY "trainer_locations.html"  "templates"
call :COPY "trainer_menu.html"       "templates"
call :COPY "trainer_money.html"      "templates"
call :COPY "trainer_numbers.html"    "templates"
call :COPY "trainer_phrases.html"    "templates"
call :COPY "trainer_pictures.html"   "templates"
call :COPY "trainer_quiz.html"       "templates"
call :COPY "trainer_sentences.html"  "templates"
call :COPY "trainer_text.html"       "templates"
call :COPY "trainer_time.html"       "templates"
call :COPY "trainer_verbs.html"      "templates"
call :COPY "trainer_video.html"      "templates"
call :COPY "trainer_weather.html"    "templates"
call :COPY "trainer_weekdays.html"   "templates"
call :COPY "trainer_words.html"      "templates"


:: --- Clean up indexed duplicates ---

:: Root
call :CLEAN "app"               ".py"
call :CLEAN "bot"               ".py"
call :CLEAN "analyze_project"   ".py"
call :CLEAN "requirements"      ".txt"
call :CLEAN "README"            ".md"

:: CSS
call :CLEAN "style"              ".css"
call :CLEAN "trainer_base"       ".css"
call :CLEAN "pictures_retell"    ".css"

:: JS
call :CLEAN "trainer_base"       ".js"
call :CLEAN "grammar_highlight"  ".js"

:: JSON
call :CLEAN "cards"              ".json"
call :CLEAN "grammar"            ".json"
call :CLEAN "lesson_1"           ".json"
call :CLEAN "phrases"            ".json"
call :CLEAN "pictures"           ".json"
call :CLEAN "sentences"          ".json"
call :CLEAN "texts"              ".json"
call :CLEAN "verbs"              ".json"
call :CLEAN "words-data"         ".json"

:: HTML
call :CLEAN "base"               ".html"
call :CLEAN "dashboard"          ".html"
call :CLEAN "history"            ".html"
call :CLEAN "login"              ".html"
call :CLEAN "register"           ".html"
call :CLEAN "select_student"     ".html"
call :CLEAN "trainer_alphabet"   ".html"
call :CLEAN "trainer_base"       ".html"
call :CLEAN "trainer_cards"      ".html"
call :CLEAN "trainer_colors"     ".html"
call :CLEAN "trainer_dates"      ".html"
call :CLEAN "trainer_grammar"    ".html"
call :CLEAN "trainer_hub"        ".html"
call :CLEAN "trainer_locations"  ".html"
call :CLEAN "trainer_menu"       ".html"
call :CLEAN "trainer_money"      ".html"
call :CLEAN "trainer_numbers"    ".html"
call :CLEAN "trainer_phrases"    ".html"
call :CLEAN "trainer_pictures"   ".html"
call :CLEAN "trainer_quiz"       ".html"
call :CLEAN "trainer_sentences"  ".html"
call :CLEAN "trainer_text"       ".html"
call :CLEAN "trainer_time"       ".html"
call :CLEAN "trainer_verbs"      ".html"
call :CLEAN "trainer_video"      ".html"
call :CLEAN "trainer_weather"    ".html"
call :CLEAN "trainer_weekdays"   ".html"
call :CLEAN "trainer_words"      ".html"

:: Self
call :CLEAN "update_techercab"   ".bat"

echo.
if %COUNT%==0 (
    if %CLEANED%==0 (
        echo  No new files found in Downloads.
    )
)
if not %COUNT%==0 (
    echo  ----------------------------------------
    echo  Updated: %COUNT% file(s)
)
if not %CLEANED%==0 (
    echo  Cleaned: %CLEANED% duplicate(s)
)
echo  ========================================
echo.
pause
exit /b


:COPY
set "FILE=%~1"
set "DEST=%~2"
set "SRC=%DL%\%FILE%"
if "!DEST!"=="." (
    set "DST=%PROJECT%%FILE%"
) else (
    set "DST=%PROJECT%%DEST%\%FILE%"
)

if not exist "!SRC!" exit /b

if not "!DEST!"=="." (
    if not exist "%PROJECT%%DEST%\" mkdir "%PROJECT%%DEST%\"
)

copy /Y "!SRC!" "!DST!" >nul 2>nul
if errorlevel 1 (
    echo  [FAIL] %FILE%
    exit /b
)

:: Delete from Downloads after successful copy
del "!SRC!" >nul 2>nul
echo  [OK] %FILE%  --^>  %DEST%\   (deleted from Downloads)
set /a COUNT+=1
exit /b


:CLEAN
:: Delete files like "name (1).py", "name (2).py" ... "name (9).py" from Downloads
set "NAME=%~1"
set "EXT=%~2"
for /L %%i in (1,1,9) do (
    if exist "%DL%\!NAME! (%%i)!EXT!" (
        del "%DL%\!NAME! (%%i)!EXT!" >nul 2>nul
        echo  [DEL] !NAME! (%%i)!EXT!  (old duplicate)
        set /a CLEANED+=1
    )
)
exit /b

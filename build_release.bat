@echo off
cd /d "%~dp0"

for /f "usebackq tokens=1,* delims==" %%A in (`python -c "from ui.app_info import APP_PACKAGE_NAME, APP_VERSION, APP_RELEASE_LABEL; print(f'APP_NAME={APP_PACKAGE_NAME}'); print(f'APP_VERSION={APP_VERSION}'); print(f'RELEASE_LABEL={APP_RELEASE_LABEL}')"`) do set "%%A=%%B"

if "%RELEASE_LABEL%"=="" (
    set "ZIP_NAME=%APP_NAME%-v%APP_VERSION%.zip"
) else (
    set "ZIP_NAME=%APP_NAME%-v%APP_VERSION%-%RELEASE_LABEL%.zip"
)

if exist dist\%APP_NAME% (
    echo Removing previous dist folder...
    rmdir /s /q dist\%APP_NAME%
)

if exist dist\%ZIP_NAME% del /q dist\%ZIP_NAME%

echo Building %APP_NAME%...
python -m PyInstaller --clean --noconfirm SheerHeartAttack.spec
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

if exist build (
    echo.
    echo Removing build folder...
    rmdir /s /q build
)

echo.
echo Creating release zip...
tar -a -c -f dist\%ZIP_NAME% -C dist %APP_NAME%
if errorlevel 1 (
    echo.
    echo Zip creation failed.
    pause
    exit /b 1
)

echo.
echo Build complete.
echo Output: dist\%APP_NAME%\%APP_NAME%.exe
echo Release zip: dist\%ZIP_NAME%
pause

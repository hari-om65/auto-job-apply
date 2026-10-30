import os
import platform
import shutil

# ARM Linux (e.g. Oracle Cloud free servers): Selenium cannot download Chrome there, so use the system chromedriver.
# Child processes (the LinkedIn bot) inherit it.
if platform.system() == "Linux" and platform.machine() in ("aarch64", "arm64") and shutil.which("chromedriver"):
    os.environ.setdefault("SE_CHROMEDRIVER", shutil.which("chromedriver"))

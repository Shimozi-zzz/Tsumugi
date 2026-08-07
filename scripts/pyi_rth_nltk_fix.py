# PyInstaller runtime hook: 在应用代码执行前设置 NLTK 安全钩子禁用变量
# 解决打包后 NLTK 3.10+ inisec 阻止 xml/regex 等从 CWD 导入的问题
import os

os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")

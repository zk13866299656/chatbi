"""开发启动入口:在 backend 目录下执行 python run.py"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)

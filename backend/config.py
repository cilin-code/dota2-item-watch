"""项目配置"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "饰品监测"

    # Steam Market
    steam_currency: int = 23       # CNY (人民币)
    steam_appid: int = 570         # Dota 2
    steam_request_delay: float = 2.0

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000

    class Config:
        env_file = ".env"


settings = Settings()

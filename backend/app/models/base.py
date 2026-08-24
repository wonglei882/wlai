"""SQLAlchemy 声明式基类（独立文件，打破循环导入）"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()

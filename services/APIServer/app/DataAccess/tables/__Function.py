import uuid_utils as uuidu
import uuid
from typing import Iterable
from pydantic import BaseModel, Field, create_model

def create_uuid7() -> uuid.UUID:
    uuid_util = uuidu.uuid7()
    return uuid.UUID(str(uuid_util))

def subset_model(
    name: str,
    base: type[BaseModel],
    include: Iterable[str],
    *,
    make_optional: bool = False,   # 例如用在 PATCH：全部變 Optional
):
    """從母模型建立子模型
    Args:
        - *name (str): 子模型名稱
        - *base (type[BaseModel]): 母模型類別
        - *include (Iterable[str]): 欄位名稱清單
        - make_optional (bool, optional): 是否將所有欄位變 Optional. Defaults to False.
    Returns:
        type[BaseModel]: 子模型類別
    """
    fields = {}
    for key in include:
        f = base.model_fields[key]  # Pydantic v2：欄位定義（含 Field 限制）
        ann = f.annotation
        default = f if f.is_required() else f.default  # 直接沿用 FieldInfo 或 default
        if make_optional and f.is_required():
            ann = ann | None     # 變 Optional
            default = None
        fields[key] = (ann, default)
    return create_model(name, **fields)  # 產生新模型類別
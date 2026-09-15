"""商品相关的 Pydantic 数据模型。

历史上商品接口直接透传 ``dict``（见 README「已知限制」）。这里把对外暴露的
商品结构收敛为显式模型，既做了出入参校验，也让 OpenAPI 文档具备准确 schema。

字段与 ``data/products.json`` 对齐；为了兼容前端可能携带的额外展示字段，
统一开启 ``extra="allow"``，避免数据文件新增字段时接口直接 422。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductSpecModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str
    label_en: str | None = None
    value: str
    value_en: str | None = None


class ProductImageModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    variant: str
    url: str | None = None
    svg: str | None = None


class ProductModel(BaseModel):
    """单个商品。"""

    model_config = ConfigDict(extra="allow")

    id: str
    sku: str
    name: str
    name_en: str | None = None
    tagline: str
    tagline_en: str | None = None
    description: str
    description_en: str | None = None
    price: float
    msrp: float | None = None
    currency: str | None = "CNY"
    category: str
    variants: list[str] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)
    stock: Literal["in_stock", "low_stock", "preorder", "soldout"] = "in_stock"
    accent_hex: str | None = None
    specs: list[ProductSpecModel] = Field(default_factory=list)
    images: list[str | ProductImageModel] = Field(default_factory=list)


class CategoryCountModel(BaseModel):
    key: str
    count: int


class ProductListResponse(BaseModel):
    """商品列表响应。"""

    items: list[ProductModel]
    total: int
    categories: list[CategoryCountModel]

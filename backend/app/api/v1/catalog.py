from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.category import Category
from app.models.department import Department
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.catalog import CategoryCreate, CategoryRead, DepartmentCreate, DepartmentRead
from app.security.deps import require_roles

router = APIRouter(tags=["catalog"])


@router.get("/departments", response_model=list[DepartmentRead])
async def list_departments(db: AsyncSession = Depends(get_db)) -> list[Department]:
    result = await db.execute(select(Department).order_by(Department.name))
    return list(result.scalars())


@router.post(
    "/departments",
    response_model=DepartmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_department(
    payload: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> Department:
    existing = await db.scalar(select(Department).where(Department.name == payload.name))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Department already exists."
        )
    department = Department(**payload.model_dump())
    db.add(department)
    await db.commit()
    await db.refresh(department)
    return department


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)) -> list[Category]:
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars())


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> Category:
    existing = await db.scalar(select(Category).where(Category.name == payload.name))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category already exists.")
    if payload.default_department_id:
        department = await db.get(Department, payload.default_department_id)
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Department not found."
            )
    category = Category(**payload.model_dump())
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: UUID,
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> Category:
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    existing = await db.scalar(
        select(Category).where(Category.name == payload.name, Category.id != category_id)
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category already exists.")
    if payload.default_department_id:
        department = await db.get(Department, payload.default_department_id)
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Department not found."
            )
    for key, value in payload.model_dump().items():
        setattr(category, key, value)
    await db.commit()
    await db.refresh(category)
    return category

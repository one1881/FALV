from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerListResponse
)
from app.services.customer_service import CustomerService
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customers", tags=["客户管理"])


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    customer_data: CustomerCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建客户"""
    try:
        service = CustomerService(db)
        customer = service.create_customer(customer_data)
        logger.info(f"Customer created: {customer.name} by user {current_user.username}")
        return customer
    except Exception as e:
        logger.exception(f"Create customer error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建客户失败"
        )


@router.get("", response_model=CustomerListResponse)
async def get_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取客户列表"""
    try:
        service = CustomerService(db)
        customers, total = service.get_customers(
            page=page,
            page_size=page_size,
            search=search
        )

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": customers
        }
    except Exception as e:
        logger.exception(f"Get customers error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取客户列表失败"
        )


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取客户详情"""
    try:
        service = CustomerService(db)
        customer = service.get_customer(customer_id)

        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="客户不存在"
            )

        return customer
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Get customer error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取客户详情失败"
        )


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    customer_data: CustomerUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新客户"""
    try:
        service = CustomerService(db)
        customer = service.update_customer(customer_id, customer_data)

        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="客户不存在"
            )

        logger.info(f"Customer updated: {customer.name} by user {current_user.username}")
        return customer
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Update customer error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新客户失败"
        )


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除客户"""
    try:
        service = CustomerService(db)
        success = service.delete_customer(customer_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="客户不存在"
            )

        logger.info(f"Customer {customer_id} deleted by user {current_user.username}")
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Delete customer error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除客户失败"
        )

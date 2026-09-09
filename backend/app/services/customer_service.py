from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerUpdate
from typing import Optional, List


class CustomerService:
    def __init__(self, db: Session):
        self.db = db

    def create_customer(self, customer_data: CustomerCreate) -> Customer:
        """创建客户"""
        customer = Customer(
            name=customer_data.name,
            code=customer_data.code,
            contact_person=customer_data.contact_person,
            phone=customer_data.phone,
            email=customer_data.email,
            address=customer_data.address,
            legal_representative=customer_data.legal_representative,
            unified_social_credit_code=customer_data.unified_social_credit_code,
            notes=customer_data.notes
        )

        self.db.add(customer)
        self.db.commit()
        self.db.refresh(customer)
        return customer

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        """获取客户详情"""
        return self.db.query(Customer).filter(Customer.id == customer_id).first()

    def get_customers(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None
    ) -> tuple[List[Customer], int]:
        """获取客户列表"""
        query = self.db.query(Customer)

        # 搜索
        if search:
            query = query.filter(
                or_(
                    Customer.name.ilike(f"%{search}%"),
                    Customer.code.ilike(f"%{search}%"),
                    Customer.contact_person.ilike(f"%{search}%")
                )
            )

        # 总数
        total = query.count()

        # 分页
        customers = (
            query.order_by(Customer.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return customers, total

    def update_customer(
        self,
        customer_id: int,
        customer_data: CustomerUpdate
    ) -> Optional[Customer]:
        """更新客户"""
        customer = self.get_customer(customer_id)
        if not customer:
            return None

        update_data = customer_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(customer, field, value)

        self.db.commit()
        self.db.refresh(customer)
        return customer

    def delete_customer(self, customer_id: int) -> bool:
        """删除客户"""
        customer = self.get_customer(customer_id)
        if not customer:
            return False

        self.db.delete(customer)
        self.db.commit()
        return True

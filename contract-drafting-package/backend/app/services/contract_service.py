from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from app.models.contract import Contract
from app.schemas.contract import ContractCreate, ContractUpdate
from typing import Optional, List
from datetime import datetime
from app.models.user import User


class ContractService:
    def __init__(self, db: Session):
        self.db = db

    def generate_contract_number(self) -> str:
        """生成合同编号"""
        prefix = datetime.now().strftime("CT%Y%m%d")

        # 查找今天最后一个合同编号
        last_contract = (
            self.db.query(Contract)
            .filter(Contract.contract_number.like(f"{prefix}%"))
            .order_by(Contract.contract_number.desc())
            .first()
        )

        if last_contract:
            last_num = int(last_contract.contract_number[-4:])
            new_num = last_num + 1
        else:
            new_num = 1

        return f"{prefix}{new_num:04d}"

    def create_contract(self, contract_data: ContractCreate, user_id: int) -> Contract:
        """创建合同"""
        contract = Contract(
            contract_number=self.generate_contract_number(),
            title=contract_data.title,
            contract_type=contract_data.contract_type,
            customer_id=contract_data.customer_id,
            customer_name=contract_data.customer_name,
            amount=contract_data.amount,
            currency=contract_data.currency,
            start_date=contract_data.start_date,
            end_date=contract_data.end_date,
            signing_date=contract_data.signing_date,
            content=contract_data.content,
            created_by=user_id,
            status='draft'
        )

        self.db.add(contract)
        self.db.commit()
        self.db.refresh(contract)
        return contract

    def get_contract(self, contract_id: int) -> Optional[Contract]:
        """获取合同详情"""
        return self.db.query(Contract).filter(Contract.id == contract_id).first()

    def get_contracts(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        contract_type: Optional[str] = None,
        search: Optional[str] = None,
        user: Optional[User] = None
    ) -> tuple[List[Contract], int]:
        """获取合同列表。

        角色数据隔离：
        - reviewer（审核员）：只看已提交审核的合同（待审核/已通过/已驳回），看不到起草中的
        - user（律师）：只看自己创建的合同
        - user=None（工作台统计等场景）：不过滤，保持全量
        """
        query = self.db.query(Contract)

        # 状态过滤
        if status:
            query = query.filter(Contract.status == status)

        # 类型过滤
        if contract_type:
            query = query.filter(Contract.contract_type == contract_type)

        # 搜索
        if search:
            query = query.filter(
                or_(
                    Contract.title.ilike(f"%{search}%"),
                    Contract.contract_number.ilike(f"%{search}%"),
                    Contract.customer_name.ilike(f"%{search}%")
                )
            )

        # 角色数据隔离
        if user is not None:
            if user.role == "reviewer":
                query = query.filter(Contract.status.in_(["pending", "approved", "rejected"]))
            else:
                query = query.filter(Contract.created_by == user.id)

        # 总数
        total = query.count()

        # 分页
        contracts = (
            query.order_by(Contract.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return contracts, total

    def update_contract(
        self,
        contract_id: int,
        contract_data: ContractUpdate
    ) -> Optional[Contract]:
        """更新合同"""
        contract = self.get_contract(contract_id)
        if not contract:
            return None

        update_data = contract_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(contract, field, value)

        self.db.commit()
        self.db.refresh(contract)
        return contract

    def delete_contract(self, contract_id: int) -> bool:
        """删除合同"""
        contract = self.get_contract(contract_id)
        if not contract:
            return False

        self.db.delete(contract)
        self.db.commit()
        return True

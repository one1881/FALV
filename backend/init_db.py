"""
数据库初始化脚本
创建所有表并添加测试数据
"""
import sys
sys.path.insert(0, '.')

from app.core.database import engine, Base, SessionLocal
from app.models.user import User
from app.models.customer import Customer
from app.models.contract import Contract
from app.models.document import Document, DocumentTemplate
from app.models.litigation import (
    CaseIntakeDraft,
    CaseParty,
    CauseOpinion,
    EvidenceExtract,
    EvidenceItem,
    FactEvidenceLink,
    FactIssue,
    JurisdictionOpinion,
    LitigationCase,
    LitigationIntake,
    LitigationMaterial,
    LitigationWorkflowResult,
    MaterialAnalysisResult,
    MaterialConfirmationBlock,
)
from app.models.review import ReviewRecord
from app.models.workflow import (
    ApprovalStep,
    ApprovalWorkflow,
    ContractArchiveRecord,
    ContractWorkflowRun,
    WorkflowReport,
)
from app.core.security import get_password_hash
from sqlalchemy import text

def init_database():
    """初始化数据库"""
    print("正在创建数据库表...")

    # 创建所有表
    Base.metadata.create_all(bind=engine)

    print("数据库表创建完成！")

    # 添加测试数据
    db = SessionLocal()
    try:
        # 初始化阶段只保证两类账号存在；已有数据库请执行 migrate_users.py 清理旧账号。
        users = [
            User(
                username='admin',
                password_hash=get_password_hash('password123'),
                full_name='业务用户',
                email='admin@example.com',
                role='user'
            ),
            User(
                username='reviewer',
                password_hash=get_password_hash('password123'),
                full_name='审核员',
                email='reviewer@example.com',
                role='reviewer'
            ),
        ]

        created_users = 0
        for user in users:
            if not db.query(User).filter(User.username == user.username).first():
                db.add(user)
                created_users += 1

        db.commit()
        print(f"已确保起草用户和审核员账号存在，新增 {created_users} 个")

        # 创建测试客户
        print("正在添加测试客户...")
        customers = [
            Customer(
                name='北京科技有限公司',
                code='CUS001',
                contact_person='张三',
                phone='13800138000',
                email='zhangsan@example.com',
                address='北京市朝阳区',
                legal_representative='李四',
                unified_social_credit_code='91110000000000000X'
            ),
            Customer(
                name='上海贸易公司',
                code='CUS002',
                contact_person='王五',
                phone='13900139000',
                email='wangwu@example.com',
                address='上海市浦东新区'
            ),
        ]

        for customer in customers:
            db.add(customer)

        db.commit()
        print(f"已创建 {len(customers)} 个测试客户")

        print("\n数据库初始化完成！")
        print("\n测试账号:")
        print("  admin/password123 (业务用户)")
        print("  reviewer/password123 (审核员)")

    except Exception as e:
        print(f"初始化失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_database()

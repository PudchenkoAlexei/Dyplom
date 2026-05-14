import asyncio
import os

from sqlalchemy import select, update

from app.db.session import AsyncSessionLocal
from app.models.category import Category
from app.models.department import Department
from app.models.enums import UserRole
from app.models.model import ModelPrediction
from app.models.ticket import Ticket
from app.models.user import User
from app.security.passwords import hash_password


DEPARTMENTS = [
    {
        "name": "Приймальна комісія КПІ ім. Ігоря Сікорського",
        "description": "Питання вступу, конкурсного відбору, правил прийому та подачі документів вступника.",
        "contact_url": "https://pk.kpi.ua/",
    },
    {
        "name": "Департамент організації освітнього процесу",
        "description": "Розклад, сесія, атестація, практики та загальні правила організації освітнього процесу.",
        "contact_url": "https://kpi.ua/about-doop",
    },
    {
        "name": "Департамент навчально-виховної роботи",
        "description": "Координація студентських питань, стипендіального та соціального супроводу.",
        "contact_url": "https://dnvr.kpi.ua/",
    },
    {
        "name": "Відділ стипендіального забезпечення",
        "description": "Академічні та соціальні стипендії, стипендіальні рейтинги, виплати.",
        "contact_url": "https://kpi.ua/stipend",
    },
    {
        "name": "Відділ супроводження документів здобувачів вищої освіти",
        "description": "Документи про вищу освіту, дипломи, додатки до дипломів, дублікати.",
        "contact_url": "https://kpi.ua/vsdzvo",
    },
    {
        "name": "Студмістечко КПІ ім. Ігоря Сікорського",
        "description": "Гуртожитки, поселення, проживання, побутові питання та оплата проживання.",
        "contact_url": "https://studmisto.kpi.ua/",
    },
    {
        "name": "Центр телекомунікацій КПІ-Телеком",
        "description": "Інтернет, мережа, корпоративна пошта, Wi-Fi та телекомунікаційні сервіси.",
        "contact_url": "https://kpi.ua/university-departments/83-kpi-telecom",
    },
    {
        "name": "Служба підтримки Електронного кампусу / КБІС",
        "description": "Питання входу, пароля, ролей, кураторів і помилок Електронного кампусу.",
        "contact_url": "https://ecampus.kpi.ua/uk/support",
    },
    {
        "name": "Управління бухгалтерського обліку та звітності",
        "description": "Оплата навчання, договори, рахунки, борги, платіжні документи.",
        "contact_url": "https://contact.kpi.ua/uboz",
    },
    {
        "name": "Центр міжнародної освіти",
        "description": "Іноземні студенти, запрошення, посвідки, легалізація та супровід навчання іноземців.",
        "contact_url": "https://kpi.ua/kpi_cmo",
    },
    {
        "name": "Відділ академічної мобільності",
        "description": "Обміни, Erasmus, learning agreement, стажування, міжнародні освітні програми.",
        "contact_url": "https://kpi.ua/vam",
    },
    {
        "name": "Департамент безпеки",
        "description": "Безпека, пропускний режим, перепустки, доступ до корпусів та інциденти.",
        "contact_url": "https://www.kpi.ua/security_department",
    },
    {
        "name": "Науково-технічна бібліотека ім. Г. І. Денисенка",
        "description": "Бібліотечні послуги, електронні ресурси, читацький квиток, каталог.",
        "contact_url": "https://kpi.ua/about/library",
    },
    {
        "name": "Відділ соціально-психологічної роботи - Студентська соціальна служба",
        "description": "Психологічна допомога, соціальна підтримка, складні життєві обставини.",
        "contact_url": "https://kpi.ua/ru/web_sss",
    },
    {
        "name": "Деканат або дирекція факультету / інституту",
        "description": "Довідки про навчання, локальні заяви, питання групи, кафедри, гаранта освітньої програми.",
        "contact_url": "https://kpi.ua/kpi_faculty",
    },
    {
        "name": "Загальна довідкова служба КПІ",
        "description": "Звернення, які потребують уточнення або первинної маршрутизації.",
        "contact_url": "https://kpi.ua/contact",
    },
]


CATEGORIES = [
    (
        "стипендія",
        "Академічні та соціальні стипендії, рейтинги, виплати.",
        "Відділ стипендіального забезпечення",
    ),
    (
        "гуртожиток / проживання",
        "Поселення, проживання, побут, ремонт, оплата гуртожитку.",
        "Студмістечко КПІ ім. Ігоря Сікорського",
    ),
    (
        "вступ",
        "Вступна кампанія, правила прийому, документи вступника, підготовчі курси для абітурієнтів.",
        "Приймальна комісія КПІ ім. Ігоря Сікорського",
    ),
    (
        "навчальний процес",
        "Розклад, сесія, практики, атестація, загальні правила освітнього процесу.",
        "Департамент організації освітнього процесу",
    ),
    (
        "деканат / довідки студентів",
        "Довідки про навчання, денна форма, довідки для роботодавця, індивідуальні заяви.",
        "Деканат або дирекція факультету / інституту",
    ),
    (
        "документи про освіту",
        "Дипломи, додатки до дипломів, дублікати, апостиль, довідки про справжність документів про освіту.",
        "Відділ супроводження документів здобувачів вищої освіти",
    ),
    (
        "переведення / поновлення / відрахування",
        "Поновлення, переведення, академвідпустка, відрахування, зміна форми навчання.",
        "Деканат або дирекція факультету / інституту",
    ),
    (
        "академічна мобільність",
        "Програми обміну, Erasmus, learning agreement, стажування.",
        "Відділ академічної мобільності",
    ),
    (
        "соціальна / психологічна підтримка",
        "Психологічна допомога, соціальний супровід, складні життєві обставини.",
        "Відділ соціально-психологічної роботи - Студентська соціальна служба",
    ),
    (
        "мережа / пошта / інтернет",
        "Wi-Fi, інтернет, мережа, VPN, Moodle-доступ, корпоративна пошта, телекомунікаційні сервіси.",
        "Центр телекомунікацій КПІ-Телеком",
    ),
    (
        "Електронний кампус",
        "Вхід, пароль, куратор групи, ролі, оцінки, журнал та помилки Електронного кампусу.",
        "Служба підтримки Електронного кампусу / КБІС",
    ),
    (
        "бібліотека",
        "Бібліотечні послуги, електронні ресурси, Scopus, Web of Science, каталог, читацький квиток.",
        "Науково-технічна бібліотека ім. Г. І. Денисенка",
    ),
    (
        "міжнародні студенти",
        "Питання іноземних студентів, посвідки, зміна паспорта, запрошення, легалізація.",
        "Центр міжнародної освіти",
    ),
    (
        "безпека / перепустки",
        "Пропускний режим, перепустки, доступ до корпусів, інциденти.",
        "Департамент безпеки",
    ),
    (
        "оплата навчання / фінанси",
        "Оплата навчання, контракт, рахунки, борги, платіжні документи.",
        "Управління бухгалтерського обліку та звітності",
    ),
    (
        "інше",
        "Змішані, нестандартні або недостатньо визначені звернення: КПІ-стікери, екскурсії, загальні пропозиції, акредитаційні довідки про університет.",
        "Загальна довідкова служба КПІ",
    ),
]

CATEGORY_RENAMES = {
    "інше / первинна маршрутизація": "інше",
}


SEED_USERS = [
    {
        "email": "admin@kpi.ua",
        "password": "AdminPassword123!",
        "full_name": "Адміністратор Системи КПІ",
        "student_group": None,
        "role": UserRole.admin,
    },
    {
        "email": "student@kpi.ua",
        "password": "StudentPassword123!",
        "full_name": "Петренко Іван Сергійович",
        "student_group": "ІП-31",
        "role": UserRole.student,
    },
    {
        "email": "teacher@kpi.ua",
        "password": "TeacherPassword123!",
        "full_name": "Шевченко Олена Миколаївна",
        "student_group": None,
        "role": UserRole.teacher,
    },
    {
        "email": "operator1@kpi.ua",
        "password": "OperatorPassword123!",
        "full_name": "Коваленко Андрій Петрович",
        "student_group": None,
        "role": UserRole.operator,
    },
    {
        "email": "operator2@kpi.ua",
        "password": "OperatorPassword123!",
        "full_name": "Мельник Наталія Вікторівна",
        "student_group": None,
        "role": UserRole.operator,
    },
]


async def seed_catalog() -> None:
    async with AsyncSessionLocal() as db:
        desired_department_names = {item["name"] for item in DEPARTMENTS}
        desired_category_names = {name for name, _, _ in CATEGORIES}

        for old_name, new_name in CATEGORY_RENAMES.items():
            old_category = await db.scalar(select(Category).where(Category.name == old_name))
            if not old_category:
                continue

            new_category = await db.scalar(select(Category).where(Category.name == new_name))
            await db.execute(
                update(ModelPrediction)
                .where(ModelPrediction.category_name == old_name)
                .values(category_name=new_name)
            )
            if new_category:
                await db.execute(
                    update(Ticket)
                    .where(Ticket.category_id == old_category.id)
                    .values(category_id=new_category.id)
                )
                await db.delete(old_category)
            else:
                old_category.name = new_name
            await db.flush()

        department_by_name: dict[str, Department] = {}
        for item in DEPARTMENTS:
            department = await db.scalar(select(Department).where(Department.name == item["name"]))
            if not department:
                department = Department(**item)
                db.add(department)
                await db.flush()
            else:
                department.description = item["description"]
                department.contact_url = item["contact_url"]
                department.is_active = True
            department_by_name[department.name] = department

        for name, description, department_name in CATEGORIES:
            category = await db.scalar(select(Category).where(Category.name == name))
            default_department_id = department_by_name[department_name].id
            if not category:
                category = Category(
                    name=name,
                    description=description,
                    default_department_id=default_department_id,
                )
                db.add(category)
            else:
                category.description = description
                category.default_department_id = default_department_id

        obsolete_categories = await db.scalars(
            select(Category).where(~Category.name.in_(desired_category_names))
        )
        for category in obsolete_categories:
            await db.delete(category)

        obsolete_departments = await db.scalars(
            select(Department).where(~Department.name.in_(desired_department_names))
        )
        for department in obsolete_departments:
            await db.delete(department)

        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")
        if admin_email and admin_password:
            existing_admin = await db.scalar(select(User).where(User.email == admin_email.lower()))
            if existing_admin:
                existing_admin.full_name = "Адміністратор Системи КПІ"
                existing_admin.password_hash = hash_password(admin_password)
                existing_admin.role = UserRole.admin
                existing_admin.is_active = True
                existing_admin.student_group = None
            else:
                db.add(
                    User(
                        email=admin_email.lower(),
                        full_name="Адміністратор Системи КПІ",
                        student_group=None,
                        password_hash=hash_password(admin_password),
                        role=UserRole.admin,
                    )
                )

        for item in SEED_USERS:
            existing_user = await db.scalar(select(User).where(User.email == item["email"].lower()))
            if existing_user:
                existing_user.full_name = item["full_name"]
                existing_user.password_hash = hash_password(item["password"])
                existing_user.role = item["role"]
                existing_user.is_active = True
                existing_user.student_group = item["student_group"]
            else:
                db.add(
                    User(
                        email=item["email"].lower(),
                        full_name=item["full_name"],
                        student_group=item["student_group"],
                        password_hash=hash_password(item["password"]),
                        role=item["role"],
                    )
                )

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_catalog())

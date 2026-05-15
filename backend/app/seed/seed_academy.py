import os

from app.core.config import settings
from app.core.crypto import encrypt_dict
from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models.entities import Base, Branch, BusinessSetting, ChannelConfig, FaqItem, IntentDefinition, IntentKeyword, RoutingRule, Tenant, TenantBrand, TenantUserRole, User

LOCAL_SEED_ENVS = {"development", "dev", "test", "testing", "local"}
DEMO_PASSWORD = os.getenv("ACADEMY_SEED_DEMO_PASSWORD", "ChangeMe123!")

INTENTS = ["GREETING","FAQ_GENERAL","REGISTRATION","PRICING","DISCOUNTS_OFFERS","SCHEDULES","LOCATION","PAYMENT_TRANSFER","COMPLAINT","HUMAN_REQUEST","CERTIFICATES","STEP_PREP","BEGINNER_ENGLISH","WOMENS_SECTION","KIDS_SECTION","ACCREDITATION","UNKNOWN"]
TOPIC = {"GREETING":"greeting","FAQ_GENERAL":"faq_general","REGISTRATION":"registration","PRICING":"pricing","DISCOUNTS_OFFERS":"discounts_offers","SCHEDULES":"schedules","LOCATION":"location","PAYMENT_TRANSFER":"payment_transfer","COMPLAINT":"complaint","HUMAN_REQUEST":"human_request","CERTIFICATES":"certificates","STEP_PREP":"step_prep","BEGINNER_ENGLISH":"beginner_english","WOMENS_SECTION":"womens_section","KIDS_SECTION":"kids_section","ACCREDITATION":"accreditation","UNKNOWN":"faq_general"}
FAQS = {
"greeting":"مرحباً بك في معهد صرح المعرفة. كيف نقدر نساعدك؟ يمكنك السؤال عن الرسوم، التسجيل، المواعيد، الموقع، الدفع أو الشهادات.",
"faq_general":"أهلاً بك في معهد صرح المعرفة. فضلاً وضح استفسارك أكثر حتى نساعدك بالشكل الصحيح.",
"registration":"طريقة التسجيل تكون بزيارة مقر المعهد لإجراء اختبار تحديد المستوى.",
"pricing":"رسوم الدورة 1500 ريال، ومدة الدورة شهر واحد.",
"discounts_offers":"العروض والخصومات يتم تحديثها من إدارة المعهد، وسيتم تحويلك للاستقبال للتأكد من العرض الحالي.",
"schedules":"بداية الدورات تكون مع بداية كل شهر. للاستعلام عن التوفر الحالي سيتم مساعدتك من الاستقبال.",
"location":"موقع المعهد: حي الفيحاء، شارع عبدالله السليمان، خلف البنك الأهلي.",
"payment_transfer":"وصلنا استفسارك بخصوص السداد أو التحويل. سيتم تحويل الطلب للمالية مع إشعار الاستقبال.",
"complaint":"نعتذر عن أي إزعاج. تم تسجيل طلبك كأولوية عالية وسيتم تحويله للموظف المختص.",
"human_request":"سيتم تحويلك لموظف من الفريق للرد عليك مباشرة.",
"certificates":"سيتم تحويل طلب الشهادة إلى مسؤول الشهادات مع إشعار الاستقبال.",
"step_prep":"للاستفسار عن اختبار STEP والتوفر الحالي سيتم مساعدتك من الاستقبال.",
"beginner_english":"إذا كنت ترغب بالتعلم من التأسيس، يتم تحديد المستوى في المعهد ثم توجيهك للمسار المناسب.",
"womens_section":"يوجد قسم نسائي منفصل بطاقم نسائي من مشرفة ومعلمات.",
"kids_section":"يوجد قسم خاص للأطفال وتحت إدارة نسائية. قد يحتاج الفريق للتأكد من العمر والتوفر.",
"accreditation":"المعهد معتمد من المؤسسة العامة للتدريب التقني والمهني."
}
KEYWORDS = {"GREETING":["السلام","سلام","مرحبا","اهلا"],"REGISTRATION":["اسجل","التسجيل","ابغى اسجل","تسجيل"],"PRICING":["السعر","بكم","رسوم","الاشتراك"],"DISCOUNTS_OFFERS":["خصم","عرض","عروض"],"SCHEDULES":["متى","المواعيد","صباح","مساء","بداية الدورة"],"LOCATION":["الموقع","وين","العنوان","لوكيشن"],"PAYMENT_TRANSFER":["سداد","تحويل","دفعت","تابي"],"COMPLAINT":["شكوى","مشكلة","زعلان","استرجاع"],"HUMAN_REQUEST":["ابغى موظف","موظف","اكلم احد"],"CERTIFICATES":["شهادة","الشهادة","استلام شهادة"],"STEP_PREP":["ستيب","STEP","اختبار ستيب"],"BEGINNER_ENGLISH":["من الصفر","تأسيس","تاسيس","اتعلم انجليزي"],"WOMENS_SECTION":["قسم نسائي","نساء","بنات"],"KIDS_SECTION":["اطفال","أطفال","طفل","عمر"],"ACCREDITATION":["معتمد","اعتماد"]}
ROUTING = {"GREETING":("BOT",[],False,None,"normal"),"FAQ_GENERAL":("BOT",["RECEPTION"],False,None,"normal"),"REGISTRATION":("RECEPTION",[],False,None,"normal"),"PRICING":("BOT",["RECEPTION"],False,None,"normal"),"DISCOUNTS_OFFERS":("RECEPTION",[],True,"offer_inquiry","normal"),"SCHEDULES":("RECEPTION",[],False,None,"normal"),"LOCATION":("BOT",[],False,None,"normal"),"PAYMENT_TRANSFER":("FINANCE",["RECEPTION"],True,"payment_transfer","normal"),"COMPLAINT":("OPERATIONS_STAFF",["SUPERVISOR"],True,"complaint","high"),"HUMAN_REQUEST":("RECEPTION",[],True,"human_request","normal"),"CERTIFICATES":("CERTIFICATES",["RECEPTION"],True,"certificate","normal"),"STEP_PREP":("RECEPTION",[],False,None,"normal"),"BEGINNER_ENGLISH":("RECEPTION",[],False,None,"normal"),"WOMENS_SECTION":("BOT",["RECEPTION"],False,None,"normal"),"KIDS_SECTION":("RECEPTION",[],False,None,"normal"),"ACCREDITATION":("BOT",[],False,None,"normal"),"UNKNOWN":("RECEPTION",[],False,None,"normal")}

def ensure_local_seed_allowed() -> None:
    if settings.app_env.strip().lower() not in LOCAL_SEED_ENVS:
        raise RuntimeError("Academy demo seed is local/dev-only and must not run in staging or production")


def demo_password() -> str:
    if len(DEMO_PASSWORD) < 8:
        raise RuntimeError("ACADEMY_SEED_DEMO_PASSWORD must be at least 8 characters")
    return DEMO_PASSWORD


def user(db, email, name, admin=False):
    u = db.query(User).filter(User.email == email).first()
    if not u:
        u = User(email=email, full_name=name, password_hash=hash_password(demo_password()), is_platform_admin=admin)
        db.add(u); db.flush()
    return u

def main():
    ensure_local_seed_allowed()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    t = db.query(Tenant).filter(Tenant.slug == "sarh-almarifah").first()
    if not t:
        t = Tenant(slug="sarh-almarifah", display_name="Sarh Al-Ma'rifah Institute", legal_name="معهد صرح المعرفة", timezone="Asia/Riyadh", default_lang="ar", status="active")
        db.add(t); db.flush()
    if not db.query(TenantBrand).filter(TenantBrand.tenant_id == t.id).first(): db.add(TenantBrand(tenant_id=t.id, primary_color="#5b0f20", support_phone="0591799917"))
    admin = user(db, "academy.admin@example.com", "Academy Admin")
    user(db, "platform.admin@example.com", "Platform Super Admin", True)
    staff = [(admin,"BUSINESS_ADMIN"),(user(db,"reception@example.com","Reception Team"),"OPERATIONS_STAFF"),(user(db,"ibrahim.finance@example.com","Ibrahim Finance"),"FINANCE"),(user(db,"ali.certificates@example.com","Ali Certificates"),"CERTIFICATES"),(user(db,"osama.supervisor@example.com","Osama Supervisor"),"SUPERVISOR"),(user(db,"broadcast@example.com","Broadcast Operator"),"BROADCAST_OPERATOR")]
    for u, r in staff:
        if not db.query(TenantUserRole).filter(TenantUserRole.tenant_id == t.id, TenantUserRole.user_id == u.id, TenantUserRole.role_code == r).first(): db.add(TenantUserRole(tenant_id=t.id, user_id=u.id, role_code=r))
    if not db.query(Branch).filter(Branch.tenant_id == t.id).first(): db.add(Branch(tenant_id=t.id, name="Jeddah - Al-Fayha", address="حي الفيحاء، شارع عبدالله السليمان، خلف البنك الأهلي", city="Jeddah", hours_json={"periods":[{"from":"09:00","to":"13:00"},{"from":"16:30","to":"21:30"}]}))
    for key, val in {"business_profile":{"sector":"academy"},"out_of_hours_policy":{"mode":"auto_reply_only"},"broadcast_policy":{"allowed_roles":["BUSINESS_ADMIN","BROADCAST_OPERATOR"],"scheduling":True}}.items():
        if not db.query(BusinessSetting).filter(BusinessSetting.tenant_id == t.id, BusinessSetting.key == key).first(): db.add(BusinessSetting(tenant_id=t.id, key=key, value_json=val))
    for code in INTENTS:
        if not db.query(IntentDefinition).filter(IntentDefinition.tenant_id == t.id, IntentDefinition.code == code).first(): db.add(IntentDefinition(tenant_id=t.id, code=code, label=code.replace("_"," ").title(), is_universal=code in ["GREETING","FAQ_GENERAL","PRICING","SCHEDULES","LOCATION","PAYMENT_TRANSFER","COMPLAINT","HUMAN_REQUEST","UNKNOWN"], enabled=True, default_response_topic_key=TOPIC[code]))
    for topic, answer in FAQS.items():
        if not db.query(FaqItem).filter(FaqItem.tenant_id == t.id, FaqItem.topic_key == topic).first(): db.add(FaqItem(tenant_id=t.id, topic_key=topic, arabic_answer=answer, status="active"))
    for code, phrases in KEYWORDS.items():
        for phrase in phrases:
            if not db.query(IntentKeyword).filter(IntentKeyword.tenant_id == t.id, IntentKeyword.intent_code == code, IntentKeyword.phrase == phrase).first(): db.add(IntentKeyword(tenant_id=t.id, intent_code=code, phrase=phrase, weight=3 if len(phrase)>5 else 1))
    for code, (owner, notify, handoff, ticket_type, priority) in ROUTING.items():
        if not db.query(RoutingRule).filter(RoutingRule.tenant_id == t.id, RoutingRule.intent_code == code).first(): db.add(RoutingRule(tenant_id=t.id, intent_code=code, primary_owner_role=owner, notify_roles_json=notify, handoff_required=handoff, ticket_type=ticket_type, priority=priority))
    ch = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == t.id, ChannelConfig.channel_type == "whatsapp").first()
    if not ch:
        ch = ChannelConfig(tenant_id=t.id, channel_type="whatsapp", status="not_connected", public_config_json={"enabled": True, "phone_number_id": "local-placeholder"})
        db.add(ch)
    ch.encrypted_credentials = ch.encrypted_credentials or encrypt_dict({"verify_token":"local-academy-verify-token","phone_number_id":"local-placeholder","waba_id":"pending","access_token":"pending","app_secret":"pending"})
    telegram = db.query(ChannelConfig).filter(ChannelConfig.tenant_id == t.id, ChannelConfig.channel_type == "telegram").first()
    if not telegram:
        telegram = ChannelConfig(tenant_id=t.id, channel_type="telegram", status="not_connected", public_config_json={"enabled": False, "live_send_enabled": False})
        db.add(telegram)
    telegram.encrypted_credentials = telegram.encrypted_credentials or encrypt_dict({"bot_token":"pending","secret_token":"academy-telegram-demo-secret"})
    for future in ["email","instagram","facebook","web_chat"]:
        if not db.query(ChannelConfig).filter(ChannelConfig.tenant_id == t.id, ChannelConfig.channel_type == future).first(): db.add(ChannelConfig(tenant_id=t.id, channel_type=future, status="future", public_config_json={"enabled": False}))
    db.commit(); db.close()
    password_hint = "ChangeMe123!" if DEMO_PASSWORD == "ChangeMe123!" else "(custom password from ACADEMY_SEED_DEMO_PASSWORD)"
    print(f"Local demo seed complete. Local-only demo login: academy.admin@example.com / {password_hint} / X-Tenant-Slug sarh-almarifah. Never use these credentials in staging or production.")

if __name__ == "__main__": main()

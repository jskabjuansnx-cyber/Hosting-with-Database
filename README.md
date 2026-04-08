# 🤖 Script Host Bot

بوت تيليجرام لاستضافة وتشغيل سكربتات Python و JavaScript.

## 🚀 النشر على Railway

1. ارفع المشروع على GitHub
2. أنشئ مشروعاً جديداً على [Railway](https://railway.app)
3. اربطه بـ GitHub repo
4. أضف المتغيرات البيئية:

| المتغير | الوصف |
|---------|-------|
| `BOT_TOKEN` | توكن البوت من @BotFather |
| `OWNER_ID` | معرفك على تيليجرام |
| `DATABASE_URL` | (اختياري) رابط قاعدة البيانات |

## 📁 هيكل المشروع

```
bot/
├── main.py          # نقطة الدخول
├── config.py        # الإعدادات من env
├── database.py      # SQLAlchemy models + helpers
├── runner.py        # تشغيل/إيقاف السكربتات
├── keep_alive.py    # Flask server للـ Railway
├── handlers/
│   ├── user.py      # أوامر المستخدم
│   ├── admin.py     # لوحة الأدمن
│   └── files.py     # رفع وإدارة الملفات
└── utils/
    ├── security.py  # فحص الملفات
    └── helpers.py   # أدوات مساعدة
```

## ⚙️ أوامر الأدمن

| الأمر | الوصف |
|-------|-------|
| `/ban <id>` | حظر مستخدم |
| `/unban <id>` | رفع الحظر |
| `/addadmin <id>` | إضافة أدمن |
| `/removeadmin <id>` | إزالة أدمن |
| `/subscribe <id> <أيام>` | تفعيل اشتراك |
| `/setconfig <key> <value>` | تغيير إعداد |

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('affiliate', '0002_add_new_fields_and_productclick'),
    ]

    operations = [
        migrations.AlterField(
            model_name='affiliateproduct',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, db_index=True, verbose_name='updated at'),
        ),
    ]

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('affiliate', '0001_initial'),
        ('users', '0002_remove_journal_pin'),
    ]

    operations = [
        # ------------------------------------------------------------------ #
        # Alter existing fields: expand max_length, remove null where possible
        # ------------------------------------------------------------------ #
        migrations.AlterField(
            model_name='affiliateproduct',
            name='name',
            field=models.CharField(max_length=500, verbose_name='product name'),
        ),
        migrations.AlterField(
            model_name='affiliateproduct',
            name='description',
            field=models.TextField(blank=True, default='', verbose_name='description'),
        ),
        migrations.AlterField(
            model_name='affiliateproduct',
            name='image_url',
            field=models.URLField(blank=True, default='', max_length=2000, verbose_name='image URL'),
        ),
        migrations.AlterField(
            model_name='affiliateproduct',
            name='aw_deep_link',
            field=models.URLField(
                help_text="Tracked affiliate URL — use this for the 'Buy' button",
                max_length=2000,
                verbose_name='Awin affiliate link',
            ),
        ),
        migrations.AlterField(
            model_name='affiliateproduct',
            name='category',
            field=models.CharField(blank=True, db_index=True, default='', max_length=255, verbose_name='category'),
        ),
        migrations.AlterField(
            model_name='affiliateproduct',
            name='advertiser_name',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='advertiser name'),
        ),
        migrations.AlterField(
            model_name='affiliateproduct',
            name='price',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='sale price'),
        ),

        # ------------------------------------------------------------------ #
        # Add new fields
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name='affiliateproduct',
            name='rrp_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Original retail price before discount',
                max_digits=10,
                null=True,
                verbose_name='RRP / original price',
            ),
        ),
        migrations.AddField(
            model_name='affiliateproduct',
            name='colour',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='colour'),
        ),
        migrations.AddField(
            model_name='affiliateproduct',
            name='merchant_deep_link',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Direct link to the product on the brand website (no tracking)',
                max_length=2000,
                verbose_name='merchant direct link',
            ),
        ),

        # ------------------------------------------------------------------ #
        # Add new index on price
        # ------------------------------------------------------------------ #
        migrations.AddIndex(
            model_name='affiliateproduct',
            index=models.Index(fields=['price', 'is_active'], name='affiliate_a_price_idx'),
        ),

        # ------------------------------------------------------------------ #
        # Create ProductClick model
        # ------------------------------------------------------------------ #
        migrations.CreateModel(
            name='ProductClick',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('clicked_at', models.DateTimeField(auto_now_add=True)),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='clicks',
                    to='affiliate.affiliateproduct',
                )),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='product_clicks',
                    to='users.user',
                )),
            ],
            options={
                'verbose_name': 'product click',
                'verbose_name_plural': 'product clicks',
                'ordering': ['-clicked_at'],
            },
        ),
    ]

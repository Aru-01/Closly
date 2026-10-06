import uuid
from django.db import migrations, models


def populate_click_refs_and_mappings(apps, schema_editor):
    ProductClick = apps.get_model('affiliate', 'ProductClick')
    for click in ProductClick.objects.all():
        click.click_ref = uuid.uuid4()
        click.save(update_fields=['click_ref'])

    # Pre-seed FeedAttributeMapping for DACH/EN categories and genders
    FeedAttributeMapping = apps.get_model('affiliate', 'FeedAttributeMapping')
    seed_mappings = [
        # Gender mappings
        ('all', 'gender', 'women', 'women'),
        ('all', 'gender', 'womenswear', 'women'),
        ('all', 'gender', 'damen', 'women'),
        ('all', 'gender', 'femme', 'women'),
        ('all', 'gender', 'dresses', 'women'),
        ('all', 'gender', 'skirts', 'women'),
        ('all', 'gender', 'men', 'men'),
        ('all', 'gender', 'menswear', 'men'),
        ('all', 'gender', 'herren', 'men'),
        ('all', 'gender', 'homme', 'men'),
        ('all', 'gender', 'unisex', 'unisex'),
        # Category mappings (German / English / French)
        ('all', 'category', 'kleid', 'Dresses'),
        ('all', 'category', 'kleider', 'Dresses'),
        ('all', 'category', 'dress', 'Dresses'),
        ('all', 'category', 'dresses', 'Dresses'),
        ('all', 'category', 'robe', 'Dresses'),
        ('all', 'category', 'rock', 'Skirts'),
        ('all', 'category', 'skirt', 'Skirts'),
        ('all', 'category', 'jupe', 'Skirts'),
        ('all', 'category', 'hemd', 'Shirts'),
        ('all', 'category', 'shirt', 'Shirts'),
        ('all', 'category', 'bluse', 'Blouses'),
        ('all', 'category', 'blouse', 'Blouses'),
        ('all', 'category', 'hose', 'Trousers'),
        ('all', 'category', 'trousers', 'Trousers'),
        ('all', 'category', 'pants', 'Trousers'),
        ('all', 'category', 'pantalon', 'Trousers'),
        ('all', 'category', 'jeans', 'Jeans'),
        ('all', 'category', 'jacke', 'Jackets'),
        ('all', 'category', 'jacket', 'Jackets'),
        ('all', 'category', 'mantel', 'Coats'),
        ('all', 'category', 'coat', 'Coats'),
        ('all', 'category', 'schuhe', 'Shoes'),
        ('all', 'category', 'shoes', 'Shoes'),
        ('all', 'category', 'sneakers', 'Shoes'),
        ('all', 'category', 'tasche', 'Bags'),
        ('all', 'category', 'bag', 'Bags'),
        ('all', 'category', 'uhr', 'Watches'),
        ('all', 'category', 'watch', 'Watches'),
    ]
    for src, fld, raw, norm in seed_mappings:
        FeedAttributeMapping.objects.get_or_create(
            source=src,
            field=fld,
            raw_value=raw,
            defaults={'normalized_value': norm}
        )


class Migration(migrations.Migration):

    dependencies = [
        ('affiliate', '0007_brand_catalogsyncrun_event_feedattributemapping_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_click_refs_and_mappings, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='productclick',
            name='click_ref',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                unique=True,
                help_text='Unique click reference token passed to affiliate network for conversion attribution',
                verbose_name='click reference UUID',
            ),
        ),
    ]

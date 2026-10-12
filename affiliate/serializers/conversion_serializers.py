from rest_framework import serializers
from affiliate.models import Conversion


class ConversionSerializer(serializers.ModelSerializer):
    """
    Serializer for Conversion & Transaction Attribution records (Audit CF-30).
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)

    class Meta:
        model = Conversion
        fields = [
            'id',
            'conversion_id',
            'source',
            'click_ref',
            'user',
            'product',
            'product_name',
            'brand',
            'brand_name',
            'advertiser_id',
            'order_reference',
            'status',
            'sale_amount',
            'commission_amount',
            'currency',
            'transaction_date',
            'validation_date',
            'reward_claimed',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

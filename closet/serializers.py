from rest_framework import serializers
from .models import ClosetItem

class ClosetItemSerializer(serializers.ModelSerializer):
    """
    Serializer for ClosetItem read, create, and update
    """
    per_wear_cost = serializers.ReadOnlyField()

    class Meta:
        model = ClosetItem
        fields = [
            'id',
            'name',
            'category',
            'color',
            'brand',
            'size',
            'price',
            'image',
            'times_worn',
            'per_wear_cost',
            'last_worn_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'times_worn', 'per_wear_cost', 'last_worn_at', 'created_at', 'updated_at']

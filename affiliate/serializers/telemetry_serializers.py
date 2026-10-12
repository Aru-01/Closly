from rest_framework import serializers
from affiliate.models import Event


class EventItemSerializer(serializers.Serializer):
    """
    Serializer for individual behavioral events in batch submission.
    """
    event_type = serializers.ChoiceField(choices=Event.TYPE_CHOICES)
    product_id = serializers.IntegerField()
    source = serializers.CharField(max_length=50, required=False, default='for_you')
    feed_page = serializers.IntegerField(required=False, allow_null=True)
    dwell_ms = serializers.IntegerField(required=False, allow_null=True)
    client_ts = serializers.DateTimeField(required=False, allow_null=True)


class EventBatchSerializer(serializers.Serializer):
    """
    Serializer for batch event ingestion (up to 200 events).
    """
    events = serializers.ListField(
        child=EventItemSerializer(),
        max_length=200,
        allow_empty=False,
    )

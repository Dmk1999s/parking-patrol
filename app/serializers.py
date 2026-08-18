from rest_framework import serializers
from .models import ParkingEvent, VehicleInfo, DisabledVehicle


class ParkingEventCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParkingEvent
        fields = ['observation_x', 'observation_y', 'observation_yaw']


class ParkingEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParkingEvent
        fields = '__all__'


class ParkingEventNextSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParkingEvent
        fields = ['id', 'zone_type', 'observation_x', 'observation_y',
                  'observation_yaw', 'status', 'created_at']



class ZoneUpdateSerializer(serializers.Serializer):
    vehicle_type = serializers.ChoiceField(choices=['NORMAL', 'ILLEGAL'])
    # models.ZONE_CHOICES 와 같은 목록이어야 한다 — COMPACT/EV 가 빠져 있어
    # 경차·전기차 구역 업데이트가 400 으로 거부되던 것을 모델과 일치시킴.
    zone_type    = serializers.ChoiceField(
        choices=['Not', 'NORMAL', 'COMPACT', 'DISABLED', 'EV', 'FIRE'])


class VehicleInfoCreateSerializer(serializers.Serializer):
    event_id       = serializers.IntegerField()
    plate_number   = serializers.CharField(max_length=20)
    amr_vehicle_x  = serializers.FloatField(required=False, allow_null=True)
    amr_vehicle_y  = serializers.FloatField(required=False, allow_null=True)
    ocr_image_path = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class VehicleInfoNextSerializer(serializers.ModelSerializer):
    # AMR2 도 AMR1 과 같은 면(앞판/뒤판)을 봐야 번호판이 보인다. 관측 방향은
    # 이벤트에 있으므로 조인해서 같이 내려 준다 (VehicleInfo 에 컬럼을 또
    # 만들 필요가 없다 — amr_vehicle_x/y 가 곧 그 관측점이다).
    observation_yaw = serializers.FloatField(source='event.observation_yaw',
                                             read_only=True)

    class Meta:
        model = VehicleInfo
        fields = ['id', 'event_id', 'plate_number', 'amr_vehicle_x',
                  'amr_vehicle_y', 'observation_yaw']


class DisabledVehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DisabledVehicle
        fields = ['plate_number', 'registered_at']

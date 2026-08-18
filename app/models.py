from django.db import models


ZONE_CHOICES = [
    ('Not', '주차구역 아님'),
    ('NORMAL', '일반 주차구역 (흰색 선)'),
    ('COMPACT', '경차 전용 (파란 선)'),
    ('DISABLED', '장애인 전용 (파란 선 + 휠체어 표시)'),
    ('EV', '전기차 전용 (초록 선)'),
    ('FIRE', '소방차 전용 (주황색)'),
]



class ParkingEvent(models.Model):
    VEHICLE_CHOICES = [
        ('NORMAL', 'Normal'),
        ('ILLEGAL', 'Illegal'),
    ]
    STATUS_CHOICES = [
        ('DETECTED', 'Detected'),
        ('SCANNED', 'Scanned'),
        ('WARNING_ISSUED', 'Warning Issued'),
        # 아래 둘은 AMR1 단계에서 종결되는 이벤트 — /api/parking/next/ 가
        # 같은 건을 무한 반환하지 않도록 DETECTED 에서 빼 준다.
        ('CLEARED', 'Cleared'),            # 정상 주차로 판정 (스킵)
        ('UNREACHABLE', 'Unreachable'),    # 관측점 접근 불가 (출동 생략)
    ]

    vehicle_type      = models.CharField(max_length=10, choices=VEHICLE_CHOICES, null=True, blank=True)
    zone_type         = models.CharField(max_length=10, choices=ZONE_CHOICES, null=True, blank=True)
    observation_x     = models.FloatField()
    observation_y     = models.FloatField()
    # 관측점에서 바라볼 방향(도, 월드 +X 기준 CCW). 웹캠이 어느 면(앞/뒤
    # 번호판)을 볼지 고른 결과다 — 좌표만으로는 복원할 수 없다 (같은 x 라도
    # 남쪽에서 북쪽을 볼 수도, 북쪽에서 남쪽을 볼 수도 있다).
    observation_yaw   = models.FloatField(null=True, blank=True)
    status            = models.CharField(max_length=15, choices=STATUS_CHOICES,
                                         default='DETECTED', db_index=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'parking_events'


class VehicleInfo(models.Model):
    event          = models.OneToOneField(ParkingEvent, on_delete=models.CASCADE,
                                          related_name='vehicle_info')
    plate_number   = models.CharField(max_length=20)
    ocr_image_path = models.TextField(null=True, blank=True)
    amr_vehicle_x  = models.FloatField(null=True, blank=True)
    amr_vehicle_y  = models.FloatField(null=True, blank=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vehicle_info'



class DisabledVehicle(models.Model):
    plate_number  = models.CharField(max_length=20, unique=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'disabled_vehicle'

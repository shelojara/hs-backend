# Generated manually for async Gemini recipe generation.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0044_recipemessage_gemini_response_raw"),
    ]

    operations = [
        migrations.AddField(
            model_name="recipe",
            name="generation_status",
            field=models.CharField(
                choices=[
                    ("completed", "Completed"),
                    ("pending", "Pending"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="completed",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="recipe",
            name="generation_failed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="recipe",
            name="generation_error_message",
            field=models.TextField(blank=True, default=""),
        ),
    ]

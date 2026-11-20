from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventario", "0043_fuente_acceso_plataforma")]

    operations = [
        migrations.AlterField(
            model_name="accesoplataforma",
            name="estado",
            field=models.CharField(
                choices=[
                    ("ACTIVO", "Activo"),
                    ("REVOCADO", "Revocado"),
                    ("PENDIENTE", "Pendiente"),
                ],
                db_index=True,
                default="PENDIENTE",
                max_length=12,
            ),
        ),
    ]

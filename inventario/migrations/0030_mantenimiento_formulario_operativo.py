# Generated for the JANO maintenance workflow extension.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventario", "0029_alter_asignacionradio_options_and_more")]

    operations = [
        migrations.AddField(
            model_name="mantenimientoequipo", name="causa_dano",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="mantenimientoequipo", name="actividades_preventivas",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="mantenimientoequipo", name="actividad_preventiva_otros",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="mantenimientoequipo", name="estados_entrega",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="mantenimientoequipo", name="funcionario_responsable",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="mantenimientos_equipo", to="inventario.funcionario",
                help_text="Funcionario responsable al momento de la intervención."),
        ),
    ]

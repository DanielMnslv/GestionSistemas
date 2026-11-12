from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventario', '0026_transferenciacomponentesradio'),
    ]

    operations = [
        migrations.AddField(
            model_name='puesto',
            name='latitud',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='puesto',
            name='longitud',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
    ]

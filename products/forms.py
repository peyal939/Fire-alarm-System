from django import forms
from .models import Order

class OrderFulfillmentForm(forms.Form):
    master_ids = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 5}), 
        required=False, 
        help_text="Enter Master Hardware IDs, one per line"
    )
    slave_ids = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 5}), 
        required=False, 
        help_text="Enter Slave Hardware IDs, one per line"
    )

    def __init__(self, *args, **kwargs):
        self.order = kwargs.pop('order')
        super().__init__(*args, **kwargs)
        
        if self.order.number_of_master_devices == 0:
            self.fields['master_ids'].disabled = True
            self.fields['master_ids'].help_text = "No master devices in this order."
        else:
            self.fields['master_ids'].label = f"Master IDs ({self.order.number_of_master_devices} required)"

        if self.order.number_of_slave_devices == 0:
            self.fields['slave_ids'].disabled = True
            self.fields['slave_ids'].help_text = "No slave devices in this order."
        else:
            self.fields['slave_ids'].label = f"Slave IDs ({self.order.number_of_slave_devices} required)"

    def clean(self):
        cleaned_data = super().clean()
        master_text = cleaned_data.get('master_ids', '')
        slave_text = cleaned_data.get('slave_ids', '')

        master_ids = [x.strip() for x in master_text.splitlines() if x.strip()]
        slave_ids = [x.strip() for x in slave_text.splitlines() if x.strip()]

        if len(master_ids) != self.order.number_of_master_devices:
            self.add_error('master_ids', f"Expected {self.order.number_of_master_devices} IDs, got {len(master_ids)}")
        
        if len(slave_ids) != self.order.number_of_slave_devices:
            self.add_error('slave_ids', f"Expected {self.order.number_of_slave_devices} IDs, got {len(slave_ids)}")
        
        cleaned_data['master_ids_list'] = master_ids
        cleaned_data['slave_ids_list'] = slave_ids
        return cleaned_data

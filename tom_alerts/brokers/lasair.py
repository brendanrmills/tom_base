import requests
from urllib.parse import urlencode
from crispy_forms.layout import Column, Fieldset, HTML, Layout, Row
from django import forms
from django.conf import settings

from tom_alerts.alerts import GenericQueryForm, GenericAlert, GenericBroker
from tom_targets.models import Target


LASAIR_URL = 'https://lasair-ztf.lsst.ac.uk/api'


class LasairBrokerForm(GenericQueryForm):
    objectId = forms.CharField(required=False, label='Object ID(s)', help_text='ZTF object ID or comma separated list')
    # cone = forms.CharField(required=False, label='Object Cone Search', help_text='Object RA and Dec')
    # sqlquery = forms.CharField(required=False, help_text='Make sure you ar eusing proper syntaxt')
    mjd__gt = forms.FloatField(
        required=False,
        label='Min date of last detection',
        widget=forms.TextInput(attrs={'placeholder': 'Date (MJD)'}),
        min_value=0.0
    )
    mjd__lt = forms.FloatField(
        required=False,
        label='Max date of last detection',
        widget=forms.TextInput(attrs={'placeholder': 'Date (MJD)'}),
        min_value=0.0
    )
    max_alerts = forms.IntegerField(
        required=False,
        label='Max number of alerts to return',
        initial=20,
        min_value=1
    )


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper.layout = Layout(
            HTML('''
                <p>
                Make sure you query be one of the methods below. The search function will only query by the first method input. </p>
                <p>
                Please see the <a href="https://lasair-ztf.lsst.ac.uk/cookbook/query/">Lasair website</a> for more detailed
                instructions on querying the broker. 
            '''),
            self.common_layout,
            Fieldset(
                'Object ID Search',
                # 'cone',
                'objectId',
            ),
            Fieldset(
                'Date Search',
                Row(
                    Column('mjd__gt'),
                    Column('mjd__lt')
                ),
            ),
            'max_alerts',
            
            # Fieldset(
            #     'Freeform SQL query',
            #     'sqlquery'
            # )
        )

    def clean(self):
        cleaned_data = super().clean()

        # Ensure that either cone search or sqlquery are populated
        if not (cleaned_data['objectId'] or cleaned_data['sqlquery'] or (cleaned_data['mjd__gt'] and cleaned_data['mjd__lt'])):
            raise forms.ValidationError('One of the required query methods must be populated.')

        return cleaned_data


# def get_lasair_object(objectId):
#     query = {
#             'limit': 1,
#             "token":"1ce34af3a313684e90eb86ccc22565ae33434e0f", #this is my personal brendan mills token idk how we can make this general
#             'objectIds': objectId,
#             'format': 'json',
#     }
#     url = LASAIR_URL + '/objects/?' + urlencode(query)
#     response = requests.get(url)
#     response.raise_for_status()
#     obj = response.json()[0]

#     mjdmax = obj['objectData']['jdmax']-2400000
#     ra = obj['objectData']['ramean']
#     dec = obj['objectData']['decmean']
#     glon = obj['objectData']['glonmean']
#     glat = obj['objectData']['glatmean']
#     magpsf = obj['candidates'][0]['magpsf']
#     return {
#         'alert_id': objectId,
#         'mjd': mjdmax,
#         'ra': ra,
#         'dec': dec,
#         'galactic_lng': glon,
#         'galactic_lat': glat,
#         'mag': magpsf
#     }


class LasairBroker(GenericBroker):
    """
    The ``LasairBroker`` is the interface to the Lasair alert broker. For information regarding the query format for
    Lasair, please see https://lasair.roe.ac.uk/objlist/.
    """

    name = 'Lasair'
    form = LasairBrokerForm

    def fetch_alerts(self, parameters):
        # if 'cone' in parameters and len(parameters['cone'].strip()) > 0:
        #     response = requests.post(
        #         LASAIR_URL + '/conesearch/',
        #         data={'cone': parameters['cone'], 'json': 'on'}
        #     )
        #     response.raise_for_status()
        #     print(response.content)
        #     cone_result = response.json()
        #     alerts = []
        #     for objectId in cone_result['hitlist']:
        #         alerts.append(get_lasair_object(objectId))
        #     return iter(alerts)

        if 'objectId' in parameters and len(parameters['objectId'].strip()) > 0:
            query = {
            'limit': 1,
            'token': settings.BROKER['Lasair'],
            'objectIds': parameters['objectId'],
            'format': 'json',
            }
            url = LASAIR_URL + '/objects/?' + urlencode(query)
            response = requests.get(url)
            response.raise_for_status()
            alerts = response.json()
            return iter(alerts)

        if 'mjd__gt' in parameters and 'mjd__lt' in parameters:
            query = {
                'selected': 'objects.objectId, objects.ramean, objects.decmean, objects.jdmax, sherlock_classifications.classification, sherlock_classifications.classificationReliability',
                "token":"1ce34af3a313684e90eb86ccc22565ae33434e0f",
                'tables': 'objects, sherlock_classifications',
                'conditions': f'objects.jdmax>{ parameters["mjd__gt"] + 2400000 } AND objects.jdmax<{parameters["mjd__lt"] + 2400000}',
                'limit': parameters.get('max_alerts',20),
                'offset': parameters.get('offset', 0),
                'format': 'json',
            }
            url = LASAIR_URL + '/query/?' + urlencode(query)
            response = requests.get(url)
            response.raise_for_status()
            parsed = response.json()
            return iter(parsed)

        # if 'sqlquery' in parameters and len(parameters['sqlquery'].strip()) > 0:
        #     response = requests.post(
        #         LASAIR_URL + '/objlist/',
        #         data={'sqlquery': parameters['sqlquery'], 'json': 'on', 'page': ''}
        #     )
        #     records = response.json()
        #     alerts = []
        #     for record in records:
        #         alerts.append(get_lasair_object(record['objectId']))
        #     return iter(alerts)

    def fetch_alert(self, alert_id):
        url = LASAIR_URL + '/object/' + alert_id + '/json/'
        response = requests.get(url)
        response.raise_for_status()
        parsed = response.json()
        return parsed

    def process_reduced_data(self, target, alert=None):
        pass

    def to_generic_alert(self, alert):
        try:
            return GenericAlert(
                url=f'https://lasair-ztf.lsst.ac.uk/object/{alert["objectId"]}/',
                id=alert['objectId'],
                name=alert['objectId'],
                ra=alert['ramean'],
                dec=alert['decmean'],
                timestamp=alert['jdmax']-2400000,
                mag=-999,
                score=1,  # dunno what this means ..?
            )
        except:
            return GenericAlert(
                url=f'https://lasair-ztf.lsst.ac.uk/object/{alert["objectId"]}/',
                id=alert['objectId'],
                name=alert['objectId'],
                ra=alert['objectData']['ramean'],
                dec=alert['objectData']['decmean'],
                timestamp=alert['objectData']['jdmax']-2400000,
                mag=alert['candidates'][0]['magpsf'],
                score=1,  # dunno what this means ..?
            )

    def to_target(self, alert):
        for c in alert['candidates']:
            if 'candid' in c:
                break
        return Target.objects.create(
            name=alert.get('objectId'),
            type='SIDEREAL',
            ra=alert['objectData']['ramean'],
            dec=alert['objectData']['decmean'],
            galactic_lng=alert['objectData']['glonmean'],
            galactic_lat=alert['objectData']['glatmean'],
        )

from datetime import datetime, timedelta

from astroplan import moon_illumination
from astropy import units as u
from astropy.coordinates import Angle, get_moon, SkyCoord
from astropy.time import Time
from django import template
from django.conf import settings
from django.db.models import Q
from guardian.shortcuts import get_objects_for_user
import numpy as np
from plotly import offline
from plotly.subplots import make_subplots
from plotly import graph_objs as go

from tom_observations.utils import get_sidereal_visibility
from tom_targets.models import Target, TargetExtra, TargetList
from tom_targets.forms import TargetVisibilityForm

register = template.Library()


@register.inclusion_tag('tom_targets/partials/recent_targets.html', takes_context=True)
def recent_targets(context, limit=10):
    """
    Displays a list of the most recently created targets in the TOM up to the given limit, or 10 if not specified.
    """
    user = context['request'].user
    return {'targets': get_objects_for_user(user, 'tom_targets.view_target').order_by('-created')[:limit]}


@register.inclusion_tag('tom_targets/partials/recently_updated_targets.html', takes_context=True)
def recently_updated_targets(context, limit=10):
    """
    Displays a list of the most recently updated targets in the TOM up to the given limit, or 10 if not specified.
    """
    user = context['request'].user
    return {'targets': get_objects_for_user(user, 'tom_targets.view_target').order_by('-modified')[:limit]}


@register.inclusion_tag('tom_targets/partials/target_feature.html')
def target_feature(target):
    """
    Displays the featured image for a target.
    """
    return {'target': target}


@register.inclusion_tag('tom_targets/partials/target_buttons.html')
def target_buttons(target):
    """
    Displays the Update and Delete buttons for a target.
    """
    return {'target': target}


@register.inclusion_tag('tom_targets/partials/target_data.html')
def target_data(target):
    """
    Displays the data of a target.
    """
    extras = {k['name']: target.extra_fields.get(k['name'], '') for k in settings.EXTRA_FIELDS if not k.get('hidden')}
    return {
        'target': target,
        'extras': extras
    }


@register.inclusion_tag('tom_targets/partials/target_unknown_statuses.html')
def target_unknown_statuses(target):
    return {
        'num_unknown_statuses': len(target.observationrecord_set.filter(Q(status='') | Q(status=None)))
    }


@register.inclusion_tag('tom_targets/partials/target_groups.html')
def target_groups(target):
    """
    Widget displaying groups this target is in and controls for modifying group association for the given target.
    """
    groups = TargetList.objects.filter(targets=target)
    return {'target': target,
            'groups': groups}


@register.inclusion_tag('tom_targets/partials/target_plan.html', takes_context=True)
def target_plan(context, fast_render=False, width=600, height=400, background=None, label_color=None, grid=True):
    """
    Displays form and renders plot for visibility calculation. Using this templatetag to render a plot requires that
    the context of the parent view have values for start_time, end_time, and airmass.

    :param fast_render: Render the plot on page load, defaults to the next 24hrs and 2.5 airmass
    :type fast_render: bool

    :param width: Width of generated plot
    :type width: int

    :param height: Height of generated plot
    :type width: int

    :param background: Color of the background of generated plot. Can be rgba or hex string.
    :type background: str

    :param label_color: Color of labels/tick labels. Can be rgba or hex string.
    :type label_color: str

    :param grid: Whether to show grid lines.
    :type grid: bool
    """
    request = context['request']
    plan_form = TargetVisibilityForm()
    visibility_graph = ''
    if all(request.GET.get(x) for x in ['start_time', 'end_time']) or fast_render:
        plan_form = TargetVisibilityForm({
            'start_time': request.GET.get('start_time', datetime.utcnow()),
            'end_time': request.GET.get('end_time', datetime.utcnow() + timedelta(days=1)),
            'airmass': request.GET.get('airmass', 2.5),
            'target': context['object']
        })
        if plan_form.is_valid():
            start_time = plan_form.cleaned_data['start_time']
            end_time = plan_form.cleaned_data['end_time']
            airmass_limit = plan_form.cleaned_data['airmass']
            visibility_data = get_sidereal_visibility(context['object'], start_time, end_time, 10, airmass_limit)
            plot_data = [
                go.Scatter(x=data[0], y=data[1], mode='lines', name=site) for site, data in visibility_data.items()
            ]
            layout = go.Layout(
                yaxis=dict(autorange='reversed'),
                width=width,
                height=height,
                paper_bgcolor=background,
                plot_bgcolor=background
            )
            layout.legend.font.color = label_color
            fig = go.Figure(data=plot_data, layout=layout)
            fig.update_yaxes(showgrid=grid, color=label_color, showline=True, linecolor=label_color, mirror=True)
            fig.update_xaxes(showgrid=grid, color=label_color, showline=True, linecolor=label_color, mirror=True)
            visibility_graph = offline.plot(
                fig, output_type='div', show_link=False
            )
    return {
        'form': plan_form,
        'target': context['object'],
        'visibility_graph': visibility_graph
    }


@register.inclusion_tag('tom_targets/partials/moon_distance.html')
def moon_distance(target, day_range=30, width=600, height=400, background=None, label_color=None, grid=True):
    """
    Renders plot for lunar distance from sidereal target.

    Adapted from Jamison Frost Burke's moon visibility code in Supernova Exchange 2.0, as seen here:
    https://github.com/jfrostburke/snex2/blob/0c1eb184c942cb10f7d54084e081d8ac11700edf/custom_code/templatetags/custom_code_tags.py#L196

    :param target: Target object for which moon distance is calculated
    :type target: tom_targets.models.Target

    :param day_range: Number of days to plot lunar distance
    :type day_range: int

    :param width: Width of generated plot
    :type width: int

    :param height: Height of generated plot
    :type width: int

    :param background: Color of the background of generated plot. Can be rgba or hex string.
    :type background: str

    :param label_color: Color of labels/tick labels. Can be rgba or hex string.
    :type label_color: str

    :param grid: Whether to show grid lines.
    :type grid: bool
    """
    if target.type != 'SIDEREAL':
        return {'plot': None}

    day_range = 30
    times = Time(
        [str(datetime.utcnow() + timedelta(days=delta)) for delta in np.arange(0, day_range, 0.2)],
        format='iso', scale='utc'
    )

    obj_pos = SkyCoord(target.ra, target.dec, unit=u.deg)
    moon_pos = get_moon(times)

    separations = moon_pos.separation(obj_pos).deg
    phases = moon_illumination(times)

    distance_color = 'rgb(0, 0, 255)'
    phase_color = 'rgb(255, 0, 0)'
    plot_data = [
        go.Scatter(x=times.mjd-times[0].mjd, y=separations, mode='lines', name='Moon distance (degrees)',
                   line=dict(color=distance_color)),
        go.Scatter(x=times.mjd-times[0].mjd, y=phases, mode='lines', name='Moon phase', yaxis='y2',
                   line=dict(color=phase_color))
    ]
    layout = go.Layout(
                xaxis={'title': 'Days from now'},
                yaxis={'range': [0, 180], 'tick0': 0, 'dtick': 45, 'tickfont': {'color': distance_color}},
                yaxis2={'range': [0, 1], 'tick0': 0, 'dtick': 0.25, 'overlaying': 'y', 'side': 'right',
                        'tickfont': {'color': phase_color}},
                margin={'l': 20, 'r': 10, 'b': 30, 't': 40},
                width=width,
                height=height,
                autosize=True,
                paper_bgcolor=background,
                plot_bgcolor=background
            )
    layout.legend.font.color = label_color
    fig = go.Figure(data=plot_data, layout=layout)
    fig.update_yaxes(showgrid=grid, color=label_color, showline=True, linecolor=label_color, mirror=True)
    fig.update_xaxes(showgrid=grid, color=label_color, showline=True, linecolor=label_color, mirror=True)
    moon_distance_plot = offline.plot(
        fig, output_type='div', show_link=False
    )

    return {'plot': moon_distance_plot}

@register.inclusion_tag('tom_targets/partials/classif_plot.html')
def classif_plot(target, width=700, height=700, background=None, label_color=None, grid=True):
    """
    Displays the classification data for a target
    """
    tcs = target.targetclassification_set.all()
    alerce_tcs = tcs.filter(source='ALeRCE')
    lasair_tcs = tcs.filter(source='Lasair')
    fink_tcs = tcs.filter(source='Fink')

    objs = ['Bogus', 'Asteroid', 'Solar System Object', 'YSO', 'CV/Nova', 'Microlensing', 'Eclipsing Binary', 'Rotating', 'SNIa', 'SNIb/c', 'SNII', 'SLSN', 'SN Other', 'Blazar', 'Quasar', 'AGN Other', 'LPV', 'Cepheid', 'RR Lyrae', 'del Scuti', 'Pulsating Other', 'Other', 'Unknown']
    fig = go.Figure(go.Barpolar(
        r=[1,1,1,1,1],
        theta=['Quasar', 'SNII', 'RR Lyrae', 'Bogus', 'Microlensing'],
        width=[3, 5, 5, 5, 5],
        marker_color=["#E4FF87", '#709BFF', '#B6FFB4', '#FFAA70', '#FFDF70'],
        opacity=0.15,
        hovertext=['AGN Types', 'Supernovae', 'Pulsating', 'Other', 'Extrinisc Variability'],
        hoverinfo='text',
        name='Groupings'
    ))

    #delas with lasair
    if lasair_tcs:#checks to make sure there are lasair classifications
        tc = lasair_tcs[len(lasair_tcs)-1]
        las_cat = ''
        las_prob = 0
        lasair_table=[#table of equivs
            ['VS', 'CV', 'SN', 'ORPHAN', 'AGN', 'NT'],
            ['RR Lyrae', 'CV/Nova', 'SNII', 'Unknown', 'Quasar', 'AGN Other'],
            [5, 1, 5, 1, 3, 1],
        ]
        try:
            i = lasair_table[0].index(tc.classification)
            las_cat = lasair_table[1][i]
            las_prob = tc.probability
            las_width = lasair_table[2][i]
        except:
            las_width = 0
        fig.add_trace(go.Barpolar(
            name="Lasair",
            r=[las_prob],
            theta=[las_cat],
            width=[las_width],
            marker= dict(line_width=2, line_color='green', color='rgba(0,0,0,0)',),
            base=0,
            hovertext=['Lasair: ' + tc.classification],
            hoverinfo='text',
        ))
    # deals with alerce
    alerce_stamp_cats = []
    alerce_stamp_probs = []
    alerce_stamp_widths = []
    stamp_table = [
        ['bogus', 'asteroid', 'SN', 'AGN', 'VS'],#what the classification is
        ['Bogus', 'Asteroid', 'SNII', 'Quasar', 'RR Lyrae'],#where to point the bar
        [1,1,5,3,5]#how thick to make the bar
    ]
    for tc in alerce_tcs.filter(level='stamp_classifier'):
        try:
            i = stamp_table[0].index(tc.classification)
            alerce_stamp_cats.append(stamp_table[1][i])
            alerce_stamp_widths.append(stamp_table[2][i])
            alerce_stamp_probs.append(tc.probability)
        except:
            pass
    fig.add_trace(go.Barpolar(#alerce stamp bar chart
        name='ALeRCE Stamp',
        r=alerce_stamp_probs,
        theta=alerce_stamp_cats,
        width=alerce_stamp_widths,
        marker_color='#8E44AD',
        marker_line_color="black",
        marker_line_width=2,
        opacity=0.8,
        base=0,
        ))

    bogus_or_asteroid = True
    if alerce_stamp_probs and alerce_stamp_cats[np.argmax(alerce_stamp_probs)] != 'asteroid' and alerce_stamp_cats[np.argmax(alerce_stamp_probs)] != 'bogus':
        bogus_or_asteroid = False    #this means it isnt bogus or an asteroid
        #this next section picks out from hte top classifier whether it is periodic, stochastic or transient
        lc_top= ''
        lc_top_prob = 0
        for tc in tcs.filter(level='lc_classifier_top'):
            if tc.probability > lc_top_prob:
                lc_top = tc.classification
                lc_top_prob = tc.probability
        alerce_lc_cats = []
        alerce_lc_probs = []
        lc_table = [
            ['E', 'DSCT', 'RRL', 'CEP', 'QSO', 'AGN', 'SNIbc', 'Periodic-Other'],#what the classification is
            ['Eclipsing Binary', 'del Scuti', 'RR Lyrae', 'Cepheid', 'Quasar', 'AGN Other', 'SNIb/c', 'Pulsating Other'],#where to point the bar
        ]
        for tc in tcs.filter(level='lc_classifier'):
            try:
                i = lc_table[0].index(tc.classification)
                alerce_lc_cats.append(lc_table[1][i])
                alerce_lc_probs.append(tc.probability)
            except:
                alerce_lc_cats.append(tc.classification)
                alerce_lc_probs.append(tc.probability)
        fig.add_trace(go.Scatterpolar(
            name='ALeRCE LC',
            r=alerce_lc_probs,
            theta=alerce_lc_cats,
            line=dict(color='#BB8FCE', width=2),
            opacity=0.8,
        ))
    
    #deals with fink,
    if fink_tcs:
        fink_cats = []
        fink_probs = []
        fink_table = [#this had not been updated for fink
            ['QSO', 'mulens', 'sso', 'KN'],#what the classification is
            ['Quasar', 'Microlensing', 'Solar System Object', 'SN Other'],#where to point the bar
        ]
        for tc in fink_tcs:
            try:
                i = fink_table[0].index(tc.classification)
                fink_cats.append(fink_table[1][i])
                fink_probs.append(tc.probability)
            except:
                fink_cats.append(tc.classification)
                fink_probs.append(tc.probability)
        fig.add_trace(go.Scatterpolar(
            name='Fink',
            r=fink_probs,
            theta=fink_cats,
            line=dict(color='#EB984E', width=2),
            opacity=0.8,
        ))
        print(fink_probs)


    fig.update_layout(
        template=None,
        height=height,
        width=width,
        polar = dict(
            # radialaxis = dict(showticklabels=False, ticks=''),
            angularaxis = dict(
                categoryarray=objs,
                categoryorder='array',
                showticklabels=True,
                )
        )
    )
    ring_prob = [None, 0.15, 0.05, 0.75, 0.05, 0]
    to_add = [
        ['Quasar'],
        ['AGN'],
        [5],
        [.85]
    ]
    fig =go.Figure(go.Sunburst(
        labels=[target.name, 'Extrinsic Variability', 'Supernova', 'AGN', 'Pulsating', 'Other'] + to_add[0],
        parents=['', target.name,  target.name, target.name, target.name, target.name, ] + to_add[1],
        values=[None, 14, 12, 10, 2, 6] + to_add[2],
        marker=dict(
            colors=ring_prob + to_add[3],
            colorscale='Greens',
            cmid=0.5),
            hovertemplate='<b>%{label} </b> <br> Probability: %{color}',
    ))
    fig.update_layout(
        margin = dict(t=0, l=0, r=0, b=0),
        height=height,
        width=width,)

    plot_out = offline.plot(
        fig, output_type='div', show_link=False
    )

    return {'plot': plot_out}

@register.inclusion_tag('tom_targets/partials/target_distribution.html')
def target_distribution(targets):
    """
    Displays a plot showing on a map the locations of all sidereal targets in the TOM.
    """
    locations = targets.filter(type=Target.SIDEREAL).values_list('ra', 'dec', 'name')
    data = [
        dict(
            lon=[location[0] for location in locations],
            lat=[location[1] for location in locations],
            text=[location[2] for location in locations],
            hoverinfo='lon+lat+text',
            mode='markers',
            type='scattergeo'
        ),
        dict(
            lon=list(range(0, 360, 60))+[180]*4,
            lat=[0]*6+[-60, -30, 30, 60],
            text=list(range(0, 360, 60))+[-60, -30, 30, 60],
            hoverinfo='none',
            mode='text',
            type='scattergeo'
        )
    ]
    layout = {
        'title': 'Target Distribution (sidereal)',
        'hovermode': 'closest',
        'showlegend': False,
        'geo': {
            'projection': {
                'type': 'mollweide',
            },
            'showcoastlines': False,
            'showland': False,
            'lonaxis': {
                'showgrid': True,
                'range': [0, 360],
            },
            'lataxis': {
                'showgrid': True,
                'range': [-90, 90],
            },
        }
    }
    figure = offline.plot(go.Figure(data=data, layout=layout), output_type='div', show_link=False)
    return {'figure': figure}


@register.filter
def deg_to_sexigesimal(value, fmt):
    """
    Displays a degree coordinate value in sexigesimal, given a format of hms or dms.
    """
    a = Angle(value, unit=u.degree)
    if fmt == 'hms':
        return '{0:02.0f}:{1:02.0f}:{2:05.3f}'.format(a.hms.h, a.hms.m, a.hms.s)
    elif fmt == 'dms':
        rep = a.signed_dms
        sign = '-' if rep.sign < 0 else '+'
        return '{0}{1:02.0f}:{2:02.0f}:{3:05.3f}'.format(sign, rep.d, rep.m, rep.s)
    else:
        return 'fmt must be "hms" or "dms"'


@register.filter
def target_extra_field(target, name):
    """
    Returns a ``TargetExtra`` value of the given name, if one exists.
    """
    try:
        return TargetExtra.objects.get(target=target, key=name).value
    except TargetExtra.DoesNotExist:
        return None


@register.inclusion_tag('tom_targets/partials/targetlist_select.html')
def select_target_js():
    """
    """
    return


@register.inclusion_tag('tom_targets/partials/aladin.html')
def aladin(target):
    """
    Displays Aladin skyview of the given target along with basic finder chart annotations including a compass
    and a scale bar. The resulting image is downloadable. This templatetag only works for sidereal targets.
    """
    return {'target': target}


@register.inclusion_tag('tom_targets/partials/target_table.html')
def target_table(targets):
    """
    Returns a partial for a table of targets, used in the target_list.html template
    by default
    """
    return {'targets': targets}

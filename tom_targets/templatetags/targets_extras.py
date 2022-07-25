from datetime import datetime, timedelta
import json
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

@register.inclusion_tag('tom_targets/partials/classif_sun.html')
def classif_sun(target, width=700, height=700, background=None, label_color=None, grid=True):
    tcs = target.targetclassification_set.all()
    
    alerce_lc_tcs = tcs.filter(level='lc_classifier')
    alerce_stamp_tcs= tcs.filter(level='stamp_classifier_1.0.4')
    if len(alerce_stamp_tcs) == 0:
        alerce_stamp_tcs = tcs.filter(level='stamp_classifier_1.0.0')
    lasair_tcs = tcs.filter(source='Lasair')
    fink_tcs = tcs.filter(source='Fink')

    with open('/home/bmills/bmillsWork/tom_test/mytom/broker_codes.txt') as json_file:#this loads the parentage dictionary that I made
        big_codes_dict = json.load(json_file)
    las_codes = big_codes_dict['las_codes']
    alst_codes = big_codes_dict['alerce_stamp_codes']
    allc_codes = big_codes_dict['alerce_lc_codes']
    fink_codes = big_codes_dict['fink_codes']

    codes = []
    if lasair_tcs:
        tc = lasair_tcs[len(lasair_tcs)-1]
        l_code = las_codes.get(tc.classification)
        codes.append( (l_code, 'Lasair', tc.probability) )

    # deals with alerce stamp
    for tc in alerce_stamp_tcs:
        codes.append( (alst_codes.get(tc.classification), 'Alerce stamp', tc.probability))

    #does alerce lc
    for tc in alerce_lc_tcs:
        codes.append( (allc_codes.get(tc.classification), 'Alerce LC', tc.probability))
        
    #deals with fink
    with open('/home/bmills/bmillsWork/tom_test/mytom/SIMBAD_otypes_labels.txt') as f:
        for line in f:
            [_, code, old, new] = line.split('|')
            fink_codes[old.strip()] = code.strip()
            fink_codes[new.strip()] = code.strip()
    candidate = False
    for tc in fink_tcs:
        if tc.probability > 0.1 and 'candidate' in tc.classification or 'Candidate' in tc.classification:
            candidate = True
        codes.append( (fink_codes[tc.classification], 'Fink', tc.probability))

    with open('/home/bmills/bmillsWork/tom_test/mytom/variability.txt') as json_file:
        parents_dict = json.load(json_file)

    labels = ['~Alert']
    parents = ['']
    values = [None]
    colors = [0]
    for code in codes:
        code_walker = code[0]
        confidence = code[2] #this is not statistical confidence more like a relative feeling
        if confidence < 0.01:
            continue
        lineage = [(code_walker, confidence)]
        while code_walker and code_walker != '~Alert':#this loop builds the lineage
            code_walker = parents_dict[code_walker]
            lineage.append( (code_walker, confidence) )
        lineage.append(('',-1))
        for l in lineage:
            if not l[0]:
                break
            if l[0] == '~Alert':
                continue
            if l[0] in labels:
                colors[labels.index(l[0])] += l[1]
            else:
                labels.append(l[0])
                parents.append(parents_dict[l[0]])
                values.append(1)
                colors.append(l[1])

    fig =go.Figure(go.Sunburst(
        labels=labels,
        parents=parents,
        values=colors,
        marker=dict(
            colors=colors,
            colorscale='Greens',
            colorbar=dict(
                tick0=0,
                len=0.25
                )),
    ))

    fig.update_layout(
        title={
            'text': target.name,
            'y':0.95,
            'x':0.5,
            'xanchor': 'center',
            'yanchor': 'top'},
        margin = dict(t=100, l=0, r=0, b=0),
        height=800,
        width=800,)

    plot_out = offline.plot(
        fig, output_type='div', show_link=False
    )

    return {'plot': plot_out}

@register.inclusion_tag('tom_targets/partials/classif_scatter.html')
def classif_scatter(target, width=700, height=700, background=None, label_color=None, grid=True):
    tcs = target.targetclassification_set.all()
    alerce_lc_tcs = tcs.filter(level='lc_classifier')
    alerce_stamp_tcs= tcs.filter(level='stamp_classifier_1.0.4')
    if len(alerce_stamp_tcs) == 0:
        alerce_stamp_tcs = tcs.filter(level='stamp_classifier_1.0.0')
    lasair_tcs = tcs.filter(source='Lasair')
    fink_tcs = tcs.filter(source='Fink')

    with open('/home/bmills/bmillsWork/tom_test/mytom/variability.txt') as json_file:
        parents_dict = json.load(json_file)
    
    fig = go.Figure(go.Barpolar(
        r=[1,1,1,1,1,1,1],
        theta=['AGN', 'SNII', 'RR*', 'Y*O','ast', 'Other'],
        width=[3, 5, 5, 7, 1, 3],
        marker_color=["#E4FF87", '#709BFF', '#B6FFB4', '#FFAA70', '#F242F5','#424142'],
        opacity=0.15,
        hovertext=['AGN Types', 'Supernovae', 'Pulsating', 'Stellar Variability', 'Asteroid', 'Other Variability'],
        hoverinfo='text',
        name='Groupings'
    ))
    fig.add_trace(go.Barpolar(
        r=[.1,.1,.1,.1,.1,.1],
        theta=['AGN', 'SNII', 'RR*', 'Y*O','ast', 'Other'],
        width=[3, 5, 5, 7, 1, 3],
        marker_color=["#E4FF87", '#709BFF', '#B6FFB4', '#FFAA70', '#F242F5','#424142'],
        opacity=0.8,
        hovertext=['AGN Types', 'Supernovae', 'Pulsating', 'Stellar Variability', 'Asteroid', 'Other Variability'],
        hoverinfo='text',
        base=np.ones(6)
    ))
    objs = ['SNIa', 'SNIbc', 'SNII', 'SLSN', 'SN*', 'QSO', 'AGN', 'G*', 'LP*', 'Ce*', 'RR*', 'dS*', 'Pu*', 'EB*', 'CV*', '**',  'Y*O', 'Er*', 'Ro*', 'V*', 'ast', 'grv', 'Other', '~Alert']
    
    with open('/home/bmills/bmillsWork/tom_test/mytom/broker_codes.txt') as json_file:#this loads the parentage dictionary that I made
        big_codes_dict = json.load(json_file)
    las_codes = big_codes_dict['las_codes']
    alst_codes = big_codes_dict['alerce_stamp_codes']
    allc_codes = big_codes_dict['alerce_lc_codes']
    fink_codes = big_codes_dict['fink_codes']
    #delas with lasair
    if lasair_tcs:
        tc = lasair_tcs[len(lasair_tcs)-1]
        code_walker = las_codes[tc.classification]
        while not code_walker in objs:
            code_walker = parents_dict[code_walker]
        l_code = code_walker
        l_prob = tc.probability
        fig.add_trace(go.Barpolar(
            name="Lasair",
            r=[l_prob],
            theta=[l_code],
            width=[1],
            marker= dict(line_width=2, line_color='green', color='rgba(0,0,0,0)',),
            base=0,
            hovertext=['Lasair: ' + tc.classification],
            hoverinfo='text',
        ))
    
    # deals with alerce stamp
    alst_list = []
    alst_probs = []
    for tc in alerce_stamp_tcs:
        code_walker = alst_codes[tc.classification]
        while not code_walker in objs:
            code_walker = parents_dict[code_walker]
        alst_list.append(code_walker)
        alst_probs.append(tc.probability)

    fig.add_trace(go.Barpolar(#alerce stamp bar chart
        name='ALeRCE Stamp',
        r=alst_probs,
        theta=alst_list,
        width=np.ones(5),
        marker_color='#BB8FCE',
        marker_line_color="black",
        marker_line_width=2,
        opacity=0.8,
        base=0,
        ))

    #does alerce lc
    alerce_lc_cats = []
    alerce_lc_probs = []
    for tc in alerce_lc_tcs:
        code_walker = allc_codes[tc.classification]
        while not code_walker in objs:
            code_walker = parents_dict[code_walker]
        alerce_lc_cats.append(code_walker)
        alerce_lc_probs.append(tc.probability)

    lc_out = []
    lc_out_p = []
    for o in objs:#this reorders the list to make the output nicer
        try:
            i = alerce_lc_cats.index(o)
            lc_out.append(alerce_lc_cats[i])
            lc_out_p.append(alerce_lc_probs[i])
        except:
            pass
    fig.add_trace(go.Scatterpolar(
        name='ALeRCE LC',
        r=lc_out_p,
        theta=lc_out,
        line=dict(color='#8E44AD', width=2),
        opacity=0.8,
        fill = 'toself'))

    #deals with fink,
    with open('/home/bmills/bmillsWork/tom_test/mytom/SIMBAD_otypes_labels.txt') as f:
        for line in f:
            [_, code, old, new] = line.split('|')
            fink_codes[old.strip()] = code.strip()
            fink_codes[new.strip()] = code.strip()

    #deals with fink,
    if fink_tcs:
        fink_cats = []
        fink_probs = []
        offset = 0
        for tc in fink_tcs:
            if tc.probability < 0.01:
                continue
            candidate = 'Candidate' in tc.classification or 'candidate' in tc.classification
            if candidate:
                fig.add_annotation(x=1,y=.98,text='This is a candidate target',showarrow=False)
            code_walker = fink_codes[tc.classification]
            print(tc.classification)
            while not code_walker in objs:
                code_walker = parents_dict[code_walker]
            if not code_walker == fink_codes[tc.classification]:
                offset += 0.05
                fig.add_annotation(x=1,y=1.1-offset,
                text='Fink actually thinks this is ' + tc.classification,
                showarrow=False,)
            fink_cats.append(code_walker)
            fink_probs.append(tc.probability)
        fig.add_trace(go.Scatterpolar(
            name='Fink',
            r=fink_probs,
            theta=fink_cats,
            line=dict(color='#EB984E', width=2),
            opacity=0.8,))
    fig.update_layout(
        template=None,
        height=800,
        width=800,
        polar = dict(
            # radialaxis = dict(showticklabels=False, ticks=''),
            angularaxis = dict(
                categoryarray=objs,
                categoryorder='array',
                showticklabels=True,
                )))
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

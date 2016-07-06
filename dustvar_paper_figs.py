import numpy as np
import os, sys
import compile_data
import astrogrid
import match_utils
import fsps
from sedpy import attenuation, observate
import h5py

import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.ticker import ScalarFormatter, LogFormatter
from cycler import cycler

from scipy.stats import binned_statistic_2d
from pdb import set_trace


def get_args():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', action='store_true')
    parser.add_argument('--res', default='90')
    parser.add_argument('--dust_curve', default='cardelli')
    parser.add_argument('--other', action='store_true', help='Make traditional 2d histograms based on the median value of some quantity such as dust, or sfr per bin. If false, the density of the points is used.')
    parser.add_argument('--sfh', default='full_sfh', choices=['full_sfh',
                        'sfh1000', 'sfh500', 'sfh200', 'sfh100'])
    return parser.parse_args()

def set_colormaps():
    cmap = plt.cm.gist_heat_r
    cmap2, cmap3, cmap4 = plt.cm.Blues_r, plt.cm.Purples_r, plt.cm.Greens_r
    cmap_resid = plt.cm.coolwarm

    for cm in [cmap, cmap2, cmap3, cmap4, cmap_resid]:
        cm.set_bad('0.65')
        #cm.set_under('0.75')
    return cmap, cmap2, cmap3, cmap4, cmap_resid

def create_cb(fig, axes_list, ims, ticks, cnorms=None, fmt=None, label='', labsize=14,pad=None,cbw=0.03,orientation='horizontal',extend='neither', cbarticksize=12):
    """
    Create a colorbar for an image plot (2d histogram or such). Can specify the
    ticks and orientation. This will add a new axis for the colorbar.
    """
    for i, ax in enumerate(axes_list):
        pos = ax.get_position()
        if orientation == 'horizontal':
            cax = fig.add_axes([pos.x0, pos.y1 + 0.01, pos.x1-pos.x0, cbw])
        else:
            cax = fig.add_axes([pos.x1 +0.02, pos.y0, cbw, pos.y1-pos.y0])
        if fmt == 'log':
            cform = LogFormatter(base=10, labelOnlyBase=False)
        else:
            cform = ScalarFormatter(useOffset=False)
        cb_kwargs = {'cax':cax, 'orientation': orientation, 'format':cform}
        if ticks is not None:
            cb_kwargs['ticks'] = ticks[i]
        if cnorms is not None:
            cb_kwargs['norm']=cnorms[i]

        cb = fig.colorbar(ims[i], cax=cax, orientation=orientation,
                          norm=cnorms[i], format=cform, ticks=ticks[i],
                          extend=extend)
        #cb = fig.colorbar(ims[i])#, **cb_kwargs)
        cb.ax.xaxis.set_ticks_position('top')
        cb.ax.tick_params(labelsize=cbarticksize)
        cb.set_label(label[i], size=labsize, labelpad=pad)

def make_2dhist(ax, x, y, bins, xlim=None, ylim=None, vmin=1, vmax=500, origin='lower', aspect='auto', cmap=plt.cm.Blues, interpolation='nearest'):
    """
    Make a 2d histogram of number counts binned along x and y.
    """
    hist_kwargs = {'bins': bins}
    if xlim is not None and ylim is not None:
        hist_kwargs['range'] = [xlim, ylim]
    h, xe, ye = np.histogram2d(x, y, **hist_kwargs)
    h[h < vmin] = -999
    extent = [xe[0], xe[-1], ye[0], ye[-1]]
    cnorm = mcolors.LogNorm(vmin=vmin, vmax=vmax)
    im = ax.imshow(h.T, cmap=cmap, interpolation=interpolation, extent=extent,
                   aspect=aspect, norm=cnorm, origin=origin)
    return im, cnorm, h, xe, ye

def make_2dhist_func(ax, x, y, z, func='median', bins=75, xlim=None, ylim=None,   vmin=0, vmax=1.5, origin='lower', aspect='auto', cnorm=None, cmap=plt.cm.Blues, interpolation='nearest'):
    """
    Make a 2d histogram binned along x and y colored with values in z undergone with
    func.
    Similar to histogram2d except allows for more than number counts to be in the
    histogram.
    """
    kwargs = {'statistic': func, 'bins': bins}
    if xlim is not None and ylim is not None:
        kwargs['range'] = [xlim, ylim]

    h, xe, ye, binnum = binned_statistic_2d(x, y, z, **kwargs)
    extent = [xe[0], xe[-1], ye[0], ye[-1]]
    if cnorm is None:
        cnorm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    im = ax.imshow(h.T, cmap=cmap, interpolation=interpolation, norm=cnorm,
                   aspect=aspect, extent=extent, origin='lower')
    return im, cnorm, [h, xe, ye, binnum]

def running_median(X, Y, ax, total_bins=9, min=-16.3, max=-13.7, color='r', flux_ratio=True, writetoscreen=False):
    bins = np.linspace(min, max, total_bins)
    delta = bins[1] - bins[0]
    idx = np.digitize(X, bins)
    run_med = [np.median(Y[idx==k]) for k in range(1, total_bins)]
    run_std = [np.std(Y[idx==k]) for k in range(1, total_bins)]
    run_count = [len(Y[idx==k]) for k in range(1, total_bins)]
    for pp in [1, 2, 3]:
        run_percent = [len(Y[idx==k][(Y[idx==k] < pp*run_std[k-1]) & (Y[idx==k] > - pp*run_std[k-1])]) / float(run_count[k-1]) if run_count[k-1] > 0 else -999 for k in range(1, total_bins)]
        if writetoscreen:
            print '   percent within ' + str(pp) + ' sigma: '
            print run_percent
            print run_count

    xx = [bins[j] + delta/2. for j in range(total_bins-1)]
    yy = run_med
    ax.errorbar(xx, yy, yerr=run_std, marker='o', ms=2, ls='--', color=color, mec=color, lw=3, elinewidth=2, zorder=100)

def draw_grid(ax=None):
    if ax is None:
        plt.grid(color='k', linestyle='-', linewidth=0.5, alpha=0.1,zorder=500)
    else:
        ax.grid(color='k', linestyle='-', linewidth=0.5, alpha=0.1, zorder=500)

def create_spectrum(tage=1.0):
    """
    Create a spectrum at a given age via fsps.StelalarPopulation().get_spectrum
    """
    sps = fsps.StellarPopulation()
    sps.params['sfh'] = 4
    sps.params['const'] = 1.0
    sps.params['imf_type'] = 2

    wave, s = sps.get_spectrum(tage=tage, peraa=True)
    return wave, s

def make_extfunc(wave, s, laws, lawnames, Rvs, bumps, filters, ftype='color', band='fuv'):
    """
    Returns the value of the extinction function for either color difference or flux ratio.

    Parameters
    ----------
    wave : float array
        Array of wavelengths, in \AA or Hz. Can be created by sps.get_spectrum.
    s : float array
        Spectrum in L_\odot/\AA or L_\odot/Hz. Same length as wave.
    laws : list
        List of attenuation functions; i.e., [attenuation.cardelli, attenuation.smc]
    lawnames : list
        List of names for the laws to be used for identificaiton; i.e., ['MW', 'SMC']
    Rvs : list
        List of R_V values corresponing to the attenuation laws.
    bumps : list
        List of 2175 \AA bump fractions corresponding to the attenuation laws.
    filters : sedpy.observate.filter object
        Filter object
    ftype : string, optional
        Function type desired. Either 'color' or 'flux'. Default: 'color'
    band : string, optional
        The filter to use for single filter flux plots. Either 'fuv' or 'nuv'.
        Default is 'fuv'.

    Returns
    -------
    e_fn : dict
        Dictionary containing the resulting extinction function values for each combination of the laws, Rvs, and bumps. It will be a single value at each combination if sps.get_spectrum() was called with tage>0. Otherwise it will have 188 values, one for each age. The value is accessed by 'e_fn[lawname][Rv][bump]'.

    """
    e_fn = {}
    for law, name in zip(laws, lawnames):
        e_fn[name] = {}
        for rv in Rvs:
            e_fn[name][str(rv)] = {}
            for f_bump in bumps:
                tau_lambda = law(wave, R_v=rv, f_bump=f_bump, tau_v=1.0)
                f2 = s * np.exp(-tau_lambda)
                mags_red = observate.getSED(wave, f2, filters)
                mags = observate.getSED(wave, s, filters)
                if len(filters) == 1:
                    mags_red = [mags_red]
                    mags = [mags]
                #f_nu(Jy) = 3631 * 10^(-0.4 * (mag+dm)
                fluxes_red = [3631 * 10**(-0.4 * (mag + M31_DM)) for mag in mags_red]
                fluxes = [3631 * 10**(-0.4 * (mag + M31_DM)) for mag in mags]
                #fluxes_red = [astrogrid.flux.galex_mag2flux(mags_red[i],filters[i].nick) for i in range(len(filters))]
                #fluxes = [astrogrid.flux.galex_mag2flux(mags[i],filters[i].nick) for i in range(len(filters))]
                if ftype == 'color':
                    color_diff = ((mags_red[0]-mags_red[1])-(mags[0]-mags[1]))
                    e_fn[name][str(rv)][str(f_bump)] = color_diff
                elif ftype == 'flux':
                    ind = 0 if band == 'fuv' else 1
                    e_fn[name][str(rv)][str(f_bump)] = np.log10(fluxes_red[ind] / fluxes[ind])
    return e_fn

def plot_extcurve(ax, lw=3, plot_type='color', legend=False, laws=[attenuation.cardelli], lawnames = ['MW'], filters=['galex_fuv', 'galex_nuv'], plot_laws=[('MW', '3.1', '1.0')], Rvs=np.arange(2.2, 4.4, 0.3), bumps=np.arange(0, 1.2, 0.2), colors=None, band='fuv'):

    wave, s = create_spectrum(tage=1.0)
    filters = observate.load_filters(filters)

    e_fn = make_extfunc(wave,s,laws,lawnames,Rvs,bumps,filters,ftype=plot_type, band=band)

    # set up the color scheme
    #if colors is None:
    #    n_lines = len(plot_laws)
    #    cm = plt.get_cmap(plt.cm.viridis)
    #    ax.set_prop_cycle(color=[cm(i) for i in np.linspace(0, 1, n_lines)])
    #else:
    ax.set_prop_cycle(color=colors)

    av = np.linspace(0, 2.5, 100)
    label = r'{0} $R_V={1}$, $f_{{bump}}={2}$'

    for pars in plot_laws:
        x = av
        y = av * e_fn[pars[0]][pars[1]][pars[2]]
        ax.plot(x, y, label=label.format(*pars), lw=lw)

    if legend:
        ax.legend(loc=6, bbox_to_anchor=(1.05, 0.58), fontsize=12)


def get_att(wave, att=attenuation.conroy, rv=3.1, fb=1.0, tau_v=1.0):
    tau_lambda = att(wave, R_v=rv, f_bump=fb, tau_v=tau_v)
    A_lambda = np.log10(np.exp(1)) * tau_lambda
    sel = (wave > 5489) & (wave < 5511)
    A_V = np.mean(A_lambda[sel])
    return A_lambda, A_V


def make_maps(var1, var2, var1lims=[0,10], var2lims=[0,1.5], cmap1=plt.cm.inferno, cmap2=plt.cm.inferno, extend='neither', save=False, plotname=None):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 4.5))
    plt.subplots_adjust(hspace=0.03, left=0.05, right=0.9, bottom=0.05, top=0.95)
    axlist = [ax1, ax2]
    for ax in axlist:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xticklabels([])
        ax.set_yticklabels([])

    if var1lims is None:
        var1min, var1max = np.nanmin(var1), np.nanmax(var1)
        var2min, var2max = np.nanmin(var2), np.nanmax(var2)
    else:
        var1min, var1max = var1lims[0], var1lims[1]
        var2min, var2max = var2lims[0], var2lims[1]
    dx1 = 0.05 * (var1max - var1min)
    dx2 = 0.05 * (var2max - var2min)
    cnorm1 = mcolors.Normalize(vmin=var1min-dx1, vmax=var1max+dx1)
    cnorm2 = mcolors.Normalize(vmin=var2min-dx2, vmax=var2max+dx2)

    cmap1.set_bad('0.65')
    cmap2.set_bad('0.65')
    if np.nanmin(var1) == -99.:
        cmap1 = adjust_cmap(cmap1)
    if np.nanmin(var2) == -99.:
        cmap2 = adjust_cmap(cmap2)

    im1 = ax1.imshow(var1[::-1].T, cmap=cmap1, norm=cnorm1)
    im2 = ax2.imshow(var2[::-1].T, cmap=cmap2, norm=cnorm2)

    ticks1 = np.linspace(var1min, var1max, 6)
    ticks2 = np.linspace(var2min, var2max, 6)

    pos1 = ax1.get_position()
    pos2 = ax2.get_position()

    divider1 = make_axes_locatable(ax1)
    cbax1 = divider1.append_axes('right', size="3%", pad=0.05)
    divider2 = make_axes_locatable(ax2)
    cbax2 = divider2.append_axes('right', size="3%", pad=0.05)

    ims = [im1, im2]
    cbax = [cbax1, cbax2]
    ticks = [ticks1, ticks2]
    labels = [r'$\sigma_{R_V} / R_V$', r'$\sigma_{f_{bump}} / f_{bump}$']

    for i in range(len(axlist)):
        cb = fig.colorbar(ims[i], cax=cbax[i], orientation='vertical', ticks=ticks[i], drawedges=False, extend=extend)
        #cb.ax.xaxis.set_ticks_position('right')
        cb.ax.tick_params(labelsize=12)
        cb.set_label(labels[i], size=15, labelpad=5)

    if save:
        plt.savefig(plotname)
    else:
        plt.show()




## FIGURES ##
## ------- ##
def fig_fluxratio_av(fuvdata, nuvdata, otherdata, two=False, sel=None, **kwargs):
    """
    Plot log(flux^obs / flux^syn,0) vs. A_V + dA_V/2. Includes running median.
    """

    x = otherdata['avdav']
    z = np.log10(otherdata['sSFR'])

    y0 = np.log10(fuvdata['fluxobs'] / fuvdata['fluxmodint'])
    y1 = np.log10(nuvdata['fluxobs'] / fuvdata['fluxmodint'])
    y2 = (fuvdata['magobs'] - nuvdata['magobs']) - (fuvdata['magmodint'] - nuvdata['magmodint'])

    if sel is not None:
        x, z = x[sel], z[sel]
        y0, y1, y2 = y0[sel], y1[sel], y2[sel]

    this_x, this_z = x.flatten(), z.flatten()
    this_y0, this_y1, this_y2 = y0.flatten(), y1.flatten(), y2.flatten()

    xlim = [-0.05, 1.55]
    ylim2 = [-3, 3]
    ylim = [-2.95, 1.2]
    zlim = [-14, -10]

    #xlabel = r'$A_{V, \textrm{\small SFH}} + \frac{1}{2} dA_{V, \textrm{\small SFH}}$'
    xlabel = r'$\widetilde{A_V}$'
    ylabel2 = (r'$(m_{\textrm{\small FUV}}-m_{\textrm{\small NUV}})_{\textrm{\small obs}} - (m_{\textrm{\small FUV}}-m_{\textrm{\small NUV}})_{\textrm{\small syn,0}}$')
    ylabel0 = (r'$\log \Bigg($' + fuvfluxobslab + '/' +
                  fuvfluxmodintlab + '$\Bigg)$')
    ylabel1 = (r'$\log \Bigg($' + nuvfluxobslab + '/' +
                  nuvfluxmodintlab + '$\Bigg)$')

    xlabels = [xlabel, xlabel, xlabel]
    ylabels = [ylabel0, ylabel1, ylabel2]

    zticks = np.linspace(zlim[0], zlim[-1], 5)
    cblabel = r'$\textrm{SFR}/\textrm{M}_{\star}$'
    extend='both'

    if kwargs['other']:
        func = 'median'
        cnorm = mcolors.Normalize(vmin=zlim[0], vmax=zlim[-1])
        fmt = None
        zlabel = cblabel
        extend = 'neither'
    else:
        # density of points
        func = 'count'
        zticks = [1, 2, 5, 10, 20, 50]
        vmax = zticks[-1]
        cnorm = mcolors.LogNorm(vmin=1, vmax=vmax)
        fmt = 'log'
        zlabel = 'Number of Regions'
        extend = 'max'

    hist_kwargs01 = {'func': func, 'bins': bins, 'xlim': xlim,
                   'ylim': ylim, 'cnorm': cnorm}
    hist_kwargs2 = {'func': func, 'bins': bins, 'xlim': xlim,
                   'ylim': ylim2, 'cnorm': cnorm}

    hist_kwargs = [hist_kwargs01, hist_kwargs01, hist_kwargs2]
    this_y = [this_y0, this_y1, this_y2]
    xlims, ylims = [xlim, xlim, xlim], [ylim, ylim, ylim2]

    laws = [attenuation.cardelli, attenuation.calzetti, attenuation.smc]
    plot_laws = [('MW', '3.1', '1.0'), ('Calz', '4.05', '0.0'), ('SMC', '3.1', '0.0')]
    lawnames = list(np.array(plot_laws)[:,0])
    Rvs = [float(r) for r in np.array(plot_laws)[:,1]]
    bumps = [float(r) for r in np.array(plot_laws)[:,2]]
    filters = ['galex_fuv', 'galex_nuv']

    color = ['Blue', 'Purple', 'darkorange']
    ptype = ['flux', 'flux', 'color']
    bands = ['fuv', 'nuv', None]
    lns = ['Cardelli', 'Calzetti', 'SMC']

    cmap = plt.cm.Greys_r
    cmap.set_bad('white')

    imlist, cnormlist = [], []

    fig, (ax0, ax1, ax2) = plt.subplots(1, 3, figsize=(12,4))
    ax_list = [ax0, ax1, ax2]

    for i in range(len(this_y)):
        im, cnorm, bindata = make_2dhist_func(ax_list[i], this_x, this_y[i], this_z, cmap=cmap, **hist_kwargs[i])
        imlist.append(im)
        cnormlist.append(cnorm)

        med_dust = running_median(this_x[np.isfinite(this_x)], this_y[i][np.isfinite(this_y[i])], ax_list[i], total_bins=8, min=0.2, max=1.5)

        plot_extcurve(ax_list[i], plot_type=ptype[i], laws=laws, lawnames=lawnames, filters=filters, plot_laws=plot_laws, Rvs=Rvs, bumps=bumps, lw=4, colors=color, band=bands[i])

    ax0.text(0.75, 0.9, r'\textbf{FUV}', transform=ax0.transAxes, fontsize=16)
    ax1.text(0.75, 0.9, r'\textbf{NUV}', transform=ax1.transAxes, fontsize=16)
    handles, labels = ax2.get_legend_handles_labels()
    ax2.legend(handles, lns, loc='lower right', frameon=False)

    for i, ax in enumerate(ax_list):
        draw_grid(ax=ax)
        ax.set_xlabel(xlabels[i], fontsize=AXISLABELSIZE)
        ax.set_ylabel(ylabels[i], fontsize=AXISLABELSIZE)

        ax.set_xlim(xlims[i])
        ax.set_ylim(ylims[i])
        ax.tick_params(axis='both', labelsize=14)

    plt.subplots_adjust(wspace=0.4, right=0.98, top=0.9, bottom=0.1)

    create_cb(fig, ax_list, imlist, [zticks]*3, cnormlist, label=[zlabel]*3,
              cbw=0.03, orientation='horizontal', pad=-40, fmt='linear',
              extend=extend)

    plotname = 'colordiff_flux_v_dust_density.'
    if kwargs['other']:
        plotname = plotname.replace('_density.', 'avdav.')
    plotname = os.path.join(_PLOT_DIR, plotname) + plot_kwargs['format']
    print plotname

    if kwargs['save']:
        plt.savefig(plotname, **plot_kwargs)
    else:
        plt.show()

def fig_att_curves(tage=0.0, mine=False, **kwargs):

    filters = ['galex_fuv', 'galex_nuv', 'wfc3_uvis_f475w', 'wfc3_uvis_f814w']
    filters = observate.load_filters(filters)

    wave, s = create_spectrum(tage=0.2)
    tau_lambda_calzetti = attenuation.calzetti(wave, R_v=4.05, tau_v=1.0)
    tau_lambda_cardelli = attenuation.cardelli(wave, R_v=3.10, tau_v=1.0)
    tau_lambda_smc = attenuation.smc(wave, tau_v=1.0)
    tau_lambda_me = attenuation.conroy(wave, R_v=3.01, f_bump=0.63)
    A_lambda_calzetti = np.log10(np.exp(1)) * tau_lambda_calzetti
    A_lambda_cardelli = np.log10(np.exp(1)) * tau_lambda_cardelli
    A_lambda_smc = np.log10(np.exp(1)) * tau_lambda_smc
    A_lambda_me = np.log10(np.exp(1)) * tau_lambda_me

    sel = (wave > 5489) & (wave < 5511)
    A_V_calzetti = np.mean(A_lambda_calzetti[sel])
    A_V_cardelli = np.mean(A_lambda_cardelli[sel])
    A_V_smc = np.mean(A_lambda_smc[sel])
    A_V_me = np.mean(A_lambda_me[sel])

    wave_micron = wave / 1e4

    fig = plt.figure(figsize=(8,6))
    ax = fig.add_subplot(111)
    ax2 = ax.twinx()
    ax.set_zorder(ax2.get_zorder()+1) # put ax in front of ax2
    ax.patch.set_visible(False)

    lw = 5
    color = 'black'
    zorder = 100
    ax.plot(1./wave_micron, A_lambda_cardelli/A_V_cardelli, lw=lw,
             color=color, ls='-', label='Cardelli', zorder=zorder)
    ax.plot(1./wave_micron, A_lambda_calzetti/A_V_calzetti, lw=lw,
             color=color, ls='--', label='Calzetti', zorder=zorder)
    ax.plot(1./wave_micron, A_lambda_smc/A_V_smc, lw=lw,
             color=color, ls=':', label='SMC', zorder=zorder)
    if mine:
        ax.plot(1./wave_micron, A_lambda_me/A_V_me, lw=lw,
             color='red', ls='-', label='SMC', zorder=zorder)

    textx = [0.78, 0.48, 0.22, 0.07]
    texty = 0.93
    colors = ['indigo', 'darkviolet', 'blue', 'red']
    #cc = [color['color'] for color in list(plt.rcParams['axes.prop_cycle'])]
    #colors = [cc[5], cc[0], cc[4], cc[7]]
    labels = [r'\textbf{FUV}', r'\textbf{NUV}', r'\textbf{F475W}', r'\textbf{F814W}']
    for i in range(len(filters)):
        xx = 1./(filters[i].wavelength/1e4)
        yy = filters[i].transmission
        ax2.plot(xx, yy/np.max(yy), lw=0)#, color=colors[i], label=labels[i])
        #ax2.fill_between(xx, 0, yy/np.max(yy), lw=0,label=labels[i], alpha=0.2)
        ax2.fill_between(xx, 0, yy/np.max(yy), lw=0, edgecolor=colors[i],
                         facecolor=colors[i], label=labels[i], alpha=0.2)
        ax2.text(textx[i], texty, labels[i], color=colors[i], fontsize=14, transform=ax2.transAxes)

    ax.set_ylabel(r'$A_\lambda / A_V$', fontsize=22)
    ax.set_xlabel(r'1/$\lambda$ [$\mu \textrm{m}^{-1}$]', fontsize=22)
    ax2.set_ylabel('Filter Transmission', fontsize=22, labelpad=15)
    ax.set_xlim(0.2, 8.2)
    ax.set_ylim(0, 8)
    ax2.set_ylim(0.05, 1.1)

    for a in [ax, ax2]:
        a.tick_params(axis='both', labelsize=18)

    if mine:
        plotname = os.path.join(_PLOT_DIR, 'avdav_fuvnuv_compare_mine.' + plot_kwargs['format'])
    else:
        plotname = os.path.join(_PLOT_DIR, 'avdav_fuvnuv_compare.' + plot_kwargs['format'])
    print plotname
    if kwargs['save']:
        plt.savefig(plotname, **plot_kwargs)
    else:
        plt.show()


def fig_compare_rv_fb():
    filters = ['galex_fuv', 'galex_nuv', 'wfc3_uvis_f475w', 'wfc3_uvis_f814w']
    filters = observate.load_filters(filters)


    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10,5), sharex=True, sharey=True)

    wave, s = create_spectrum(tage=0.2)
    wave_micron = wave / 1e4

    A_lambda_conroy, A_V_conroy = get_att(wave, att=attenuation.conroy, rv=3.1, fb=1.0, tau_v=1.0)

    fbrange = np.arange(0.0, 2.2, 0.2)
    rvrange = np.arange(2.0, 5.3, 0.3)


    lw = 2
    color = 'black'
    zorder = 100

    n = len(fbrange)
    color_map_cycle = [plt.get_cmap('inferno')(1. * i/n) for i in range(n)]
    ax1.set_prop_cycle(cycler('color', color_map_cycle))
    ax2.set_prop_cycle(cycler('color', color_map_cycle))

    for i in range(n):
        rv, fb = rvrange[i], fbrange[i]
        lab1 = str(rv)
        lab2 = str(fb)
        A_lambda1, x = get_att(wave, rv=rv)
        A_lambda2, x = get_att(wave, fb=fb)

        ax1.plot(1./wave_micron, A_lambda1/A_V_conroy, lw=2,label=lab1)
        ax2.plot(1./wave_micron, A_lambda2/A_V_conroy, lw=2,label=lab2)


    for i in range(len(filters)):
        xx = 1./(filters[i].wavelength/1e4)
        yy = filters[i].transmission
        cc = '0.5'
        f = 7.
        ax1.plot(xx, yy/np.max(yy)*f, lw=0)
        ax1.fill_between(xx, 0, yy/np.max(yy)*f, lw=0, edgecolor=cc,
                         facecolor=cc, alpha=0.2)
        ax2.plot(xx, yy/np.max(yy), lw=0)
        ax2.fill_between(xx, 0, yy/np.max(yy)*f, lw=0, edgecolor=cc,
                         facecolor=cc, alpha=0.2)



    labels = [r'$R_V$', r'$f_\textrm{bump}$']
    for i, ax in enumerate([ax1, ax2]):
        ax.grid()
        legend = ax.legend(loc='upper left', fontsize=12,frameon=False, title=labels[i])
        ax.tick_params(axis='both', labelsize=18)
        plt.setp(legend.get_title(),fontsize=16)
        ax.set_xlabel(r'1/$\lambda$ [$\mu \textrm{m}^{-1}$]', fontsize=22)

    ax1.set_ylabel(r'$A_\lambda / A_V$', fontsize=22)
    ax1.set_xlim(0.2, 8.2)
    ax1.set_ylim(0, 8)

    plt.subplots_adjust(wspace=0.05)
    plotname = os.path.join(_PLOT_DIR, 'rv_fb_variation_filters.pdf')
    print plotname
    if kwargs['save']:
        plt.savefig(plotname, **plot_kwargs)
    else:
        plt.show()


def fig_region_triangles(otherdata, regs=[3,2630,1087], **kwargs):
    import corner
    corner.ScalarFormatter(useOffset=False)
    h5file = os.path.join(_WORK_DIR, 'all_runs.h5')
    hf = h5py.File(h5file, 'r')
    if regs is None:
        nregs = len(hf.keys())
    else:
        nregs = regs

    #labels =[r'$\langle R_V \rangle$', r'$\langle f_{\textrm{bump}} \rangle$']
    labels = [r'$\widetilde{R_V}$', r'$\widetilde{f_{\textrm{bump}}}$']

    rvrange = [[1.4, 4.2]] * 2 + [[1.0, 10.0]]
    fbrange = [[0.0, 1.5]] * 3

    xloc1, yloc1 = 0.03, 0.8#[0.05, 0.05, 0.6], [0.9, 0.9, 0.9]
    xloc2, yloc2 = 0.03, 0.60#0[.05, 0.05, 0.6], [0.75, 0.75, 0.75]
    xloc3, yloc3 = 0.22, 0.45

    for i, r in enumerate(regs):
        av = otherdata['avdav'][np.isfinite(otherdata['avdav'])][regs[i]-1]
        sfr = otherdata['sfr100'][np.isfinite(otherdata['sfr100'])][regs[i]-1]
        avtext = r'$\widetilde{A_V}$ = ' + str(np.around(av, 2))
        sfrlabel = r'$\log$ SFR [M$_\odot$ yr$^{-1}$]'
        sfrnum = ' = ' + str(np.around(np.log10(sfr),2))
        sfrtext = sfrlabel + '\n' + sfrnum

        label_kwargs = dict(labels=labels, labelpad=-50)

        nn = 'region_dist_' + str(r).zfill(5) + '.pdf'
        plotname = os.path.join(_PLOT_DIR, nn)
        sampler = np.asarray(hf.get(hf.keys()[regs[i]-1])['sampler_flatchain'])

        #sampler = np.asarray(group['sampler_flatchain'])
        rv_med, fb_med = np.nanmedian(sampler[:,0]), np.nanmedian(sampler[:,1])
        print np.percentile(sampler[:,0], 84) -np.percentile(sampler[:,0], 16)


        fig = corner.corner(sampler[:,:], range=[rvrange[i], fbrange[i]], **label_kwargs)
        ax = fig.axes
        ax0ylim = ax[0].get_ylim()
        ax3ylim = ax[3].get_ylim()
        line_kwargs = {'lw':3, 'color':'grey', 'ls':'--', 'alpha':0.5}
        ax[0].plot([rv_med, rv_med], ax0ylim, **line_kwargs)
        ax[3].plot([fb_med, fb_med], ax3ylim, **line_kwargs)
        ax[1].text(xloc1, yloc1, avtext, transform=ax[1].transAxes, size=16)
        #ax[1].text(xloc2, yloc2, sfrtext, transform=ax[1].transAxes, size=14, va='top')
        ax[1].text(xloc2, yloc2, sfrlabel, transform=ax[1].transAxes, size=16)
        ax[1].text(xloc3, yloc3, sfrnum, transform=ax[1].transAxes, size=16)


        print plotname
        if kwargs['save']:
            plt.savefig(plotname)
        else:
            plt.show()

    hf.close()


def fig_sigma_param_distributions(otherdata, first=False, **kwargs):
    import h5py
    hf_file = os.path.join(_WORK_DIR, 'all_runs.h5')
    gridfile = os.path.join(_WORK_DIR, 'med_sig_rv_fbump_per_region.dat')
    if first:
        hf = h5py.File(hf_file, 'r')

        nregs = len(hf.keys())
        reg_range = range(nregs)
        nsamples = hf.get(hf.keys()[0])['sampler_chain'].shape[1]
        grid = np.asarray(np.zeros((nregs, 4)))
        for i, reg in enumerate(reg_range):
            group = hf.get(hf.keys()[reg])
            grid[i,0] = np.median(np.asarray(group['sampler_flatchain'][:,0]))
            grid[i,1] = np.std(np.asarray(group['sampler_flatchain'][:,0]))
            grid[i,2] = np.median(np.asarray(group['sampler_flatchain'][:,1]))
            grid[i,3] = np.std(np.asarray(group['sampler_flatchain'][:,1]))
        hf.close()
        plt.savetxt(gridfile, grid)
    else:
        grid = np.loadtxt(gridfile)

    sfr100 = otherdata['sfr100']
    shape = sfr100.shape
    sfr100flat = sfr100.flatten()
    sel = np.isfinite(sfr100flat)
    sel2 = np.isfinite(sfr100)
    avdav = otherdata['avdav']
    avdavflat = avdav.flatten()

    rv_array = np.zeros(shape).flatten()
    sig_rv_array = np.zeros(shape).flatten()
    fb_array = np.zeros(shape).flatten()
    sig_fb_array = np.zeros(shape).flatten()

    rv_array[sel] = grid[:,0]
    sig_rv_array[sel] = grid[:,1]
    fb_array[sel] = grid[:,2]
    sig_fb_array[sel] = grid[:,3]
    rv_array[~sel] = np.nan
    fb_array[~sel] = np.nan
    sig_rv_array[~sel] = np.nan
    sig_fb_array[~sel] = np.nan

    rv = rv_array.reshape(shape)
    fb = fb_array.reshape(shape)
    sig_rv = sig_rv_array.reshape(shape)
    sig_fb = sig_fb_array.reshape(shape)

    x1 = sig_rv / rv
    x2 = sig_fb / fb
    x3 = avdavflat

    x1[~sel2] = np.nan
    x2[~sel2] = np.nan

    plotname = os.path.join(_PLOT_DIR, 'av_rv_fbump_sigma_distributions')
    #make_maps(x1, x2, var1lims=[0.05, 0.5], var2lims=[0.2, 1.1], cmap1=plt.cm.inferno, cmap2=plt.cm.inferno, extend='both',save=False, plotname=None)

    var1, var2, var3 = x1, x2, avdav
    var1lims = [0.05, 0.45]
    var2lims = [0.2, 1.1]
    var3lims = [0.0, 1.5]
    extend = 'both'

    #fig = plt.figure(figsize=(7,4))
    fig = plt.figure(figsize=(7,6.0))
    ax5 = plt.subplot2grid((3,3), (0,0))
    ax6 = plt.subplot2grid((3,3), (0,1), colspan=2)
    ax1 = plt.subplot2grid((3,3), (1,0))
    ax2 = plt.subplot2grid((3,3), (1,1), colspan=2)
    ax3 = plt.subplot2grid((3,3), (2,0))
    ax4 = plt.subplot2grid((3,3), (2,1), colspan=2)

    #plt.subplots_adjust(hspace=0.03, left=0.05, right=0.9, bottom=0.05, top=0.95)
    axlist = [ax2, ax4, ax6]
    for ax in axlist:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xticklabels([])
        ax.set_yticklabels([])

    if var1lims is None:
        var1min, var1max = np.nanmin(var1), np.nanmax(var1)
        var2min, var2max = np.nanmin(var2), np.nanmax(var2)
        var3min, var3max = np.nanmin(var3), np.nanmax(var3)
    else:
        var1min, var1max = var1lims[0], var1lims[1]
        var2min, var2max = var2lims[0], var2lims[1]
        var3min, var3max = var3lims[0], var3lims[1]

    def colornorm(cmin, cmax):
        dx = 0.05 * (cmax - cmin)
        cnorm = mcolors.Normalize(vmin=cmin-dx, vmax=cmax+dx)
        return cnorm

    cnorm1 = colornorm(var1min, var1max)
    cnorm2 = colornorm(var2min, var2max)
    cnorm3 = colornorm(var3min, var3max)

    cmap1, cmap2, cmap3 = plt.cm.inferno, plt.cm.inferno, plt.cm.inferno
    cmap1.set_bad('0.65')
    cmap2.set_bad('0.65')
    cmap3.set_bad('0.65')
    if np.nanmin(var1) == -99.:
        cmap1 = adjust_cmap(cmap1)
    if np.nanmin(var2) == -99.:
        cmap2 = adjust_cmap(cmap2)
    if np.nanmin(var3) == -99.:
        cmap3 = adjust_cmap(cmap3)


    hist1 = ax1.hist(x1[np.isfinite(x1)], bins=50)
    hist2 = ax3.hist(x2[np.isfinite(x2)], bins=50)
    hist3 = ax5.hist(x3[np.isfinite(x3)], bins=50)

    im1 = ax2.imshow(var1[::-1].T, cmap=cmap1, norm=cnorm1)
    im2 = ax4.imshow(var2[::-1].T, cmap=cmap2, norm=cnorm2)
    im3 = ax6.imshow(var3[::-1].T, cmap=cmap3, norm=cnorm3)

    ticks1 = np.linspace(var1min, var1max, 6)
    ticks2 = np.linspace(var2min, var2max, 6)
    ticks3 = np.linspace(var3min, var3max, 6)

    pos1 = ax1.get_position()
    pos2 = ax2.get_position()

    divider1 = make_axes_locatable(ax2)
    cbax1 = divider1.append_axes('right', size="3%", pad=0.05)
    divider2 = make_axes_locatable(ax4)
    cbax2 = divider2.append_axes('right', size="3%", pad=0.05)
    divider3 = make_axes_locatable(ax6)
    cbax3 = divider3.append_axes('right', size="3%", pad=0.05)

    ims = [im1, im2, im3]
    cbax = [cbax1, cbax2, cbax3]
    ticks = [ticks1, ticks2, ticks3]
    labels = [r'$\widetilde{\sigma_{R_V}} / \widetilde{R_V}$', r'$\widetilde{\sigma_{f_{bump}}} / \widetilde{f_{bump}}$', r'$\widetilde{A_V}$']

    for i in range(len(cbax)):
        cb = fig.colorbar(ims[i], cax=cbax[i], orientation='vertical', ticks=ticks[i], drawedges=False, extend=extend)
        #cb.ax.xaxis.set_ticks_position('right')
        cb.ax.tick_params(labelsize=12)
        cb.set_label(labels[i], size=15, labelpad=5)

    for i, ax in enumerate([ax1, ax3, ax5]):
        ax.tick_params(axis='both', labelsize=11)
        ax.set_xlabel(labels[i], fontsize=14)

    plt.subplots_adjust(hspace=0.45, wspace=0.03, left=0.1, right=0.92, top=0.92)
    print plotname
    if kwargs['save']:
        plt.savefig(plotname)
    else:
        plt.show()


def fig_param_distributions(otherdata, first=False, **kwargs):
    gridfile = os.path.join(_WORK_DIR, 'med_sig_rv_fbump_per_region.dat')
    if first:
        import h5py
        hf_file = os.path.join(_WORK_DIR, 'all_runs.h5')
        hf = h5py.File(hf_file, 'r')

        nregs = len(hf.keys())
        reg_range = range(nregs)
        nsamples = hf.get(hf.keys()[0])['sampler_chain'].shape[1]
        grid = np.asarray(np.zeros((nregs, 4)))
        for i, reg in enumerate(reg_range):
            group = hf.get(hf.keys()[reg])
            grid[i,0] = np.median(np.asarray(group['sampler_flatchain'][:,0]))
            grid[i,1] = np.std(np.asarray(group['sampler_flatchain'][:,0]))
            grid[i,2] = np.median(np.asarray(group['sampler_flatchain'][:,1]))
            grid[i,3] = np.std(np.asarray(group['sampler_flatchain'][:,1]))
        hf.close()
        np.savetxt(gridfile, grid)
    else:
        grid = np.loadtxt(gridfile)

    xlims = [[0, 9.5], [-0.1, 2.8], [0.18, 1.39], [0.28, 0.499]]
    #sel2 = otherdata['av'][np.isfinite(otherdata['avdav'])] + otherdata['dav'][np.isfinite(otherdata['dav'])] > 1.0
    sel = otherdata['sfr100'][np.isfinite(otherdata['sfr100'])] > -9999
    sel1 = otherdata['sfr100'][np.isfinite(otherdata['sfr100'])] > 1e-5
    sel2 = otherdata['avdav'][np.isfinite(otherdata['avdav'])] > 1.0
    #sel3 = grid[:,1] < 0.75
    sel3 = grid[:,1] / grid[:,0] < 0.2
    sels = [sel, sel3, sel1, sel2]

    data, means, sig = [], [], []
    for k in range(4):
        data.append([grid[s,k] for s in sels][::-1])
        means.append([np.mean(grid[s,k]) for s in sels][::-1])
        sig.append([np.std(grid[s,k]) for s in sels][::-1])


    color = next(plt.gca()._get_lines.prop_cycler)
    c1 = color['color']
    color = next(plt.gca()._get_lines.prop_cycler)
    color = next(plt.gca()._get_lines.prop_cycler)
    c2 = color['color']
    colors = ['black', c1, c2]
    colors2 = colors[::-1]
    colors2.append('black')

    axis_colors = [u'#5DA5DA', u'#FAA43A', u'#60BD68', u'#F15854', u'#39CCCC', u'#B10DC9', u'#FFDC00', u'#85144B', u'#4D4D4D', u'#FF70B1']
    plt.close('all')

    labels = [r'$\widetilde{R_V}$', r'$\widetilde{\sigma_{R_V}}$', r'$\widetilde{f_{bump}}$',r'$\widetilde{\sigma_{f_{bump}}}$']
    sel_labels = ['All', r'$\widetilde{\sigma_{R_V}} / \widetilde{R_V} < 0.2$', 'SFR $>10^{-5}$', '$\widetilde{A_V} > 1.0$']

    fig1, ax1 = plt.subplots(2, 2, figsize=(8,7))

    for i in range(4):
        hist_args = dict(bins=50, histtype='step', lw=2, range=xlims[i])
        hist_args2 = dict(bins=50, histtype='stepfilled', lw=2, range=xlims[i])
        hist1 = ax1[i/2, i%2].hist(grid[sel,i], color=colors[0], label=sel_labels[0], **hist_args)
        hist2 = ax1[i/2, i%2].hist(grid[sel1,i], color=colors[1], label=sel_labels[2], **hist_args)
        hist3 = ax1[i/2, i%2].hist(grid[sel2,i], color=colors[2], label=sel_labels[3], **hist_args)
        hist4 = ax1[i/2, i%2].hist(grid[sel3,i], color=colors[0], alpha=0.2, zorder=-1, label=sel_labels[1], **hist_args2)

    ax1[0,0].legend(frameon=False, fontsize=12)
    for i in range(4):
        ax1[i/2, i%2].set_xlim(xlims[i])
        ax1[i/2, i%2].tick_params(axis='both', labelsize=14)
        ax1[i/2,i%2].set_xlabel(labels[i], fontsize=16)

    plt.subplots_adjust(wspace=0.2, hspace=0.28, left=0.08, right=0.96, top=0.96)
    plotname1 = os.path.join(_PLOT_DIR, 'rv_fbump_sels_distributions.pdf')
    print plotname1
    if kwargs['save']:
        plt.savefig(plotname1)
    else:
        plt.show()


    fig2, ax2 = plt.subplots(2,2, figsize=(8,7), sharey=True)
    box = dict(sym='x', vert=False)
    bp1 = ax2[0,0].boxplot(data[0], **box)
    bp2 = ax2[0,1].boxplot(data[1], **box)
    bp3 = ax2[1,0].boxplot(data[2], **box)
    bp4 = ax2[1,1].boxplot(data[3], **box)

    lw=2
    alphas = [1, 1, 0.4, 1]
    for i in range(len(bp1['boxes'])):
        box_args = dict(linewidth=lw, color=colors2[i], alpha=alphas[i])
        flier_args = dict(markersize=3, markeredgewidth=0.1, markeredgecolor=colors2[i], markerfacecolor=colors2[i], alpha=alphas[i])
        for j, bp in enumerate([bp1, bp2, bp3, bp4]):
            bp['boxes'][i].set(**box_args)
            bp['whiskers'][i*2].set(**box_args)
            bp['whiskers'][i*2+1].set(**box_args)
            bp['caps'][i*2].set(**box_args)
            bp['caps'][i*2+1].set(**box_args)
            bp['medians'][i].set(**box_args)
            bp['fliers'][i].set(**flier_args)

            ax2[j/2,j%2].plot(means[j][i], i+1, marker='*', mfc='0.4', ms=10)
            ax2[j/2,j%2].plot(means[j][i]+sig[j][i], i+1, marker='D', mfc=axis_colors[1], ms=4)
            ax2[j/2,j%2].plot(means[j][i]-sig[j][i], i+1, marker='D', mfc=axis_colors[1], ms=4)

    for i in range(4):
        ax2[i/2,i%2].set_yticklabels(sel_labels[::-1], rotation=30, fontsize=14)
        ax2[i/2,i%2].tick_params(axis='both', labelsize=14)
        ax2[i/2,i%2].tick_params(axis='x')
        ax2[i/2,i%2].grid()
        ax2[i/2,i%2].set_xlabel(labels[i], fontsize=16)
        ax2[i/2, i%2].set_xlim(xlims[i])

    plt.subplots_adjust(wspace=0.02, hspace=0.3, top=0.96, right=0.96)
    plotname2 = os.path.join(_PLOT_DIR, 'boxplot_rv_fbump_sels.pdf')
    print plotname2
    if kwargs['save']:
        plt.savefig(plotname2)
    else:
        plt.show()








def fig_boxplot(otherdata, first=False, **kwargs):
    gridfile = os.path.join(_WORK_DIR, 'med_sig_rv_fbump_per_region.dat')
    if first:
        import h5py
        hf_file = os.path.join(_WORK_DIR, 'all_runs.h5')
        hf = h5py.File(hf_file, 'r')

        nregs = len(hf.keys())
        reg_range = range(nregs)
        nsamples = hf.get(hf.keys()[0])['sampler_chain'].shape[1]
        grid = np.asarray(np.zeros((nregs, 4)))
        for i, reg in enumerate(reg_range):
            group = hf.get(hf.keys()[reg])
            grid[i,0] = np.median(np.asarray(group['sampler_flatchain'][:,0]))
            grid[i,1] = np.std(np.asarray(group['sampler_flatchain'][:,0]))
            grid[i,2] = np.median(np.asarray(group['sampler_flatchain'][:,1]))
            grid[i,3] = np.std(np.asarray(group['sampler_flatchain'][:,1]))
        hf.close()
        np.savetxt(gridfile, grid)
    else:
        grid = np.loadtxt(gridfile)

    allregs = otherdata['sfr100'][np.isfinite(otherdata['sfr100'])] > -9999
    sfr100 = otherdata['sfr100'][np.isfinite(otherdata['sfr100'])] > 1e-5
    avdav = otherdata['avdav'][np.isfinite(otherdata['avdav'])] > 1.0
    color = next(plt.gca()._get_lines.prop_cycler)
    c1 = color['color']
    color = next(plt.gca()._get_lines.prop_cycler)
    color = next(plt.gca()._get_lines.prop_cycler)
    c2 = color['color']
    colors = ['black', c1, c2][::-1]
    axis_colors = [u'#5DA5DA', u'#FAA43A', u'#60BD68', u'#F15854', u'#39CCCC', u'#B10DC9', u'#FFDC00', u'#85144B', u'#4D4D4D', u'#FF70B1']
    plt.close('all')

    sels = [allregs, sfr100, avdav]

    data, means, sig = [], [], []
    for k in range(4):
        data.append([grid[s,k] for s in sels][::-1])
        means.append([np.mean(grid[s,k]) for s in sels][::-1])
        sig.append([np.std(grid[s,k]) for s in sels][::-1])

    box = dict(sym='x', vert=False)
    fig, ax = plt.subplots(2,2, figsize=(8,7), sharey=True)
    bp1 = ax[0,0].boxplot(data[0], **box)
    bp2 = ax[0,1].boxplot(data[1], **box)
    bp3 = ax[1,0].boxplot(data[2], **box)
    bp4 = ax[1,1].boxplot(data[3], **box)

    lw=2
    for i in range(len(bp1['boxes'])):
        for j, bp in enumerate([bp1, bp2, bp3, bp4]):
            bp['boxes'][i].set(color=colors[i], linewidth=lw)
            bp['whiskers'][i*2].set(color=colors[i], linewidth=lw)
            bp['whiskers'][i*2+1].set(color=colors[i], linewidth=lw)
            bp['medians'][i].set(linewidth=lw, color='0.6')
            bp['caps'][i*2].set(linewidth=lw, color=colors[i])
            bp['caps'][i*2+1].set(linewidth=lw, color=colors[i])
            bp['fliers'][i].set(markersize=3, markeredgewidth=0.1, markeredgecolor=colors[i], markerfacecolor=colors[i])
            #set_trace()
            ax[j/2,j%2].plot(means[j][i], i+1, marker='*', mfc='0.4', ms=10)
            ax[j/2,j%2].plot(means[j][i]+sig[j][i], i+1, marker='D', mfc=axis_colors[1], ms=4)
            ax[j/2,j%2].plot(means[j][i]-sig[j][i], i+1, marker='D', mfc=axis_colors[1], ms=4)


    labels = [r'$\widetilde{R_V}$', r'$\widetilde{\sma_{R_V}}$', r'$\widetilde{f_{bump}}$',r'$\widetilde{\sigma_{f_{bump}}}$']
    for i, a in enumerate(fig.axes):
        a.set_yticklabels(['All', 'SFR $>$'+'\n'+'$10^{-5}$', '$\widetilde{A_V} > $'+'\n'+'$1.0$'][::-1], rotation=30)
        a.tick_params(axis='both', labelsize=14)
        a.tick_params(axis='x')
        #a.text(0.7, 0.85, labels[i], fontsize=16, transform=a.transAxes)
        a.grid()
        a.set_xlabel(labels[i], fontsize=16)
        #a.xaxis.set_label_position('top')

    ax[0,0].set_xlim(0.0, 9.5)
    ax[0,1].set_xlim(-0.1, 2.8)
    ax[1,0].set_xlim(0.0, 1.39)
    ax[1,1].set_xlim(0.28, 0.499)
    plt.subplots_adjust(wspace=0.02, hspace=0.3, top=0.96, right=0.96)

    plotname = os.path.join(_PLOT_DIR, 'boxplot_rv_fbump.pdf')
    print plotname
    if kwargs['save']:
        plt.savefig(plotname)
    else:
        plt.show()



def fig_ensemble_triangles(infile='/Users/alexialewis/research/PHAT/dustvar/sampler_independent/final_sampler_rv_fbump.h5', **kwargs):
    import corner
    with h5py.File(infile, 'r') as hf:
        corner.ScalarFormatter(useOffset=False)
        sampler_rv = hf.get('R_V')['sampler_flatchain']
        sampler_fb = hf.get('f_bump')['sampler_flatchain']
        labels_rv = [r'$\mu_{R_V}$', '$\sigma_{R_V}$']
        labels_fb = ['$\mu_{f_{bump}}$', '$\sigma_{f_{bump}}$']

        fig1 = corner.corner(sampler_rv,labels=labels_rv)#,range=lim)
        plotname1 = os.path.join(_PLOT_DIR, 'triangle_rv_sfrgt-5.pdf')
        if kwargs['save']:
            plt.savefig(plotname1)
        fig2 = corner.corner(sampler_fb, labels=labels_fb)
        plotname2 = os.path.join(_PLOT_DIR, 'triangle_fb_sfrgt-5.pdf')
        if kwargs['save']:
            plt.savefig(plotname2)
        if ~kwargs['save']:
            plt.show()


def fig_maps_uvdust(fuvdata, nuvdata, **kwargs):
    """
    Plot maps of the UV dust.

    """
    labels = ['$A_{FUV}$', '$A_{NUV}$']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(4,6))

    amin, amax = 0, 3.5

    cnorm = mcolors.Normalize(vmin=amin, vmax=amax)

    cmapa = plt.cm.Blues
    cmapb = plt.cm.Purples

    cmapa.set_bad('0.65')
    cmapb.set_bad('0.65')

    im1 = ax1.imshow(fuvdata['ext'], cmap=cmapa, origin=origin,
                     interpolation=interpolation, norm=cnorm)
    im2 = ax2.imshow(nuvdata['ext'], cmap=cmapb, origin=origin,
                     interpolation=interpolation, norm=cnorm)

    plt.subplots_adjust(wspace=0.08, left=0.05, right=0.95, bottom=0.05, top=0.88)

    pos1 = ax1.get_position()
    pos2 = ax2.get_position()

    ticks = np.linspace(amin, amax, 6)

    cbax1 = fig.add_axes([pos1.x0, pos1.y1+.01, pos1.x1 - pos1.x0, 0.03])
    cbax2 = fig.add_axes([pos2.x0, pos2.y1+.01, pos2.x1 - pos2.x0, 0.03])

    cb1 = fig.colorbar(im1, cax=cbax1, orientation='horizontal', extend='max',
                       ticks=ticks)
    cb1.ax.xaxis.set_ticks_position('top')
    cb1.ax.tick_params(labelsize=CBARTICKSIZE)
    cb1.set_label(r'$A_{FUV}$ [mag]', size=12, labelpad=-45)

    cb2 = fig.colorbar(im2, cax=cbax2, orientation='horizontal', extend='max',
                       ticks=ticks)
    cb2.ax.xaxis.set_ticks_position('top')
    cb2.ax.tick_params(labelsize=CBARTICKSIZE)
    cb2.set_label(r'$A_{NUV}$ [mag]', size=12, labelpad=-45)

    for i, ax in enumerate([ax1, ax2]):
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.03, 0.95, labels[i], transform=ax.transAxes,
                fontsize=PLOTTEXTSIZE)

    if kwargs['save']:
        plotname = os.path.join(_PLOT_DIR,'uv_ext_maps.'+plot_kwargs['format'])
        plt.savefig(plotname, **plot_kwargs)
    else:
        plt.show()

def fig_auv_av(fuvdata, nuvdata, otherdata, **kwargs):
    """
    Plot A^syn_FUV vs A_V + 1/2 dA_V.
    """
    avdav = otherdata['avdav']
    afuv = fuvdata['ext']
    anuv = nuvdata['ext']

    x = avdav.flatten()
    y1 = afuv.flatten()
    y2 = anuv.flatten()

    cmapa = cmap2
    cmapb = cmap3
    cmapa.set_bad('white')
    cmapb.set_bad('white')
    labelsize = 18

    xlim = [0, 1.5]
    ylim = [0, 4]
    vmin, vmax = 1, 200

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 4))

    im1, cnorm1, h1, xe1, ye1 = make_2dhist(ax1, x, y1, bins, xlim=xlim,
                                            ylim=ylim, vmin=vmin, vmax=vmax,
                                            cmap=cmapa)
    im2, cnorm2, h2, xe2, ye2 = make_2dhist(ax2, x, y2, bins, xlim=xlim,
                                            ylim=ylim, vmin=vmin, vmax=vmax,
                                            cmap=cmapb)
    ax1.plot([0, 10], [0, 10], color='k', lw=3, ls='--')
    ax2.plot([0, 10], [0, 10], color='k', lw=3, ls='--')

    for ax in [ax1, ax2]:
        draw_grid(ax=ax)
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.set_xlabel(r'$A_V + \frac{1}{2} dA_V$', fontsize=labelsize)
        ax.tick_params(axis='both', labelsize=12)

    ax1.set_ylabel(r'$A_{FUV}$', fontsize=labelsize)
    ax2.set_ylabel(r'$A_{NUV}$', fontsize=labelsize)

    plt.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.15,
                        wspace=0.35)

    if args.save:
        plotname = os.path.join(_PLOT_DIR, 'avdav_fuvnuv_compare.')
        plt.savefig(plotname + plot_kwargs['format'], **plot_kwargs)
    else:
        plt.show()


def cardelli_curves(tage=0.0, **kwargs):

    filters = ['galex_fuv', 'galex_nuv']
    filters = observate.load_filters(filters)
    fcolors = ['indigo', 'darkviolet']
    flabels = [r'\textbf{FUV}', r'\textbf{NUV}']

    wave, s = create_spectrum(tage=0.2)
    tau_lambda_cardelli = attenuation.cardelli(wave, R_v=3.10, tau_v=1.0)
    A_lambda_cardelli = np.log10(np.exp(1)) * tau_lambda_cardelli

    sel = (wave > 5489) & (wave < 5511)
    A_V_cardelli = np.mean(A_lambda_cardelli[sel])

    wave_micron = wave / 1e4

    fig = plt.figure(figsize=(8,6))
    ax = fig.add_subplot(111)
    #ax2 = ax.twinx()

    lw = 2
    color = 'black'
    zorder = 100
    ax.plot(1./wave_micron, A_lambda_cardelli/A_V_cardelli, lw=lw,
             color=color, ls='-', label='$R_V=3.1$', zorder=zorder)

    rvrange = np.arange(2.0, 5.3, 0.3)
    n = len(rvrange)
    color_map_cycle = [plt.get_cmap('plasma')(1. * i/n) for i in range(n)]
    ax.set_prop_cycle(cycler('color', color_map_cycle))

    for rv in rvrange:
        lab = str(rv)
        tau_lambda = attenuation.cardelli(wave, R_v=rv, tau_v=1.0)
        A_lambda = np.log10(np.exp(1)) * tau_lambda

        #color = next(ax._get_lines.prop_cycler)
        #c = color['color']
        ax.plot(1./wave_micron, A_lambda/A_V_cardelli, lw=2,label=lab)

    #for i in range(len(filters)):
    #    xx = 1./(filters[i].wavelength/1e4)
    #    yy = filters[i].transmission
    #    ax2.plot(xx, yy/np.max(yy), lw=0)
    #    ax2.fill_between(xx, 0, yy/np.max(yy), lw=0, edgecolor=fcolors[i],
    #                     facecolor=fcolors[i], alpha=0.2)
    ax.grid()
    ax.legend(loc='upper left')

    ax.set_ylabel(r'$A_\lambda / A_V$', fontsize=22)
    ax.set_xlabel(r'1/$\lambda$ [$\mu \textrm{m}^{-1}$]', fontsize=22)
    #ax2.set_ylabel('Filter Transmission', fontsize=22, labelpad=15)
    ax.set_xlim(0.2, 8.2)
    ax.set_ylim(0, 8)
    #ax2.set_ylim(0.05, 1.1)

    #for a in [ax, ax2]:
    ax.tick_params(axis='both', labelsize=18)

    plotname = os.path.join(_PLOT_DIR, 'rv_variation.pdf')
    print plotname
    if kwargs['save']:
        plt.savefig(plotname, **plot_kwargs)
    else:
        plt.show()


def conroy_curves(tage=0.0, **kwargs):

    filters = ['galex_fuv', 'galex_nuv']
    filters = observate.load_filters(filters)
    fcolors = ['indigo', 'darkviolet']
    flabels = [r'\textbf{FUV}', r'\textbf{NUV}']


    wave, s = create_spectrum(tage=0.2)
    tau_lambda_conroy = attenuation.conroy(wave, R_v=3.10,f_bump=1.0,tau_v=1.0)
    A_lambda_conroy = np.log10(np.exp(1)) * tau_lambda_conroy

    sel = (wave > 5489) & (wave < 5511)
    A_V_conroy= np.mean(A_lambda_conroy[sel])

    wave_micron = wave / 1e4

    fig = plt.figure(figsize=(8,6))
    ax = fig.add_subplot(111)
    #ax2 = ax.twinx()

    lw = 2
    color = 'black'
    zorder = 100
    ax.plot(1./wave_micron, A_lambda_conroy/A_V_conroy, lw=lw,
             color=color, ls='-', label=r'$f_{\rm bump}=1.0$', zorder=zorder)

    fbrange = list(np.arange(0.0, 1.0, 0.2)) + list(np.arange(1.2, 2.2, 0.2))
    n = len(fbrange)
    color_map_cycle = [plt.get_cmap('plasma')(1. * i/n) for i in range(n)]
    ax.set_prop_cycle(cycler('color', color_map_cycle))

    for fb in fbrange:
        lab = str(fb)
        tau_lambda = attenuation.conroy(wave, R_v=3.1, f_bump=fb, tau_v=1.0)
        A_lambda = np.log10(np.exp(1)) * tau_lambda

        #color = next(ax._get_lines.prop_cycler)
        #c = color['color']
        ax.plot(1./wave_micron, A_lambda/A_V_conroy, lw=2,label=lab)

    ax.grid()
    ax.legend(loc='upper left')

    ax.set_ylabel(r'$A_\lambda / A_V$', fontsize=22)
    ax.set_xlabel(r'1/$\lambda$ [$\mu \textrm{m}^{-1}$]', fontsize=22)
    #ax2.set_ylabel('Filter Transmission', fontsize=22, labelpad=15)
    ax.set_xlim(0.2, 8.2)
    ax.set_ylim(0, 8)
    #ax2.set_ylim(0.05, 1.1)

    #for a in [ax, ax2]:
    ax.tick_params(axis='both', labelsize=18)

    plotname = os.path.join(_PLOT_DIR, 'f_bump_variation.pdf')
    print plotname
    if kwargs['save']:
        plt.savefig(plotname, **plot_kwargs)
    else:
        plt.show()


def m31_dustlaw_on_data(fuvdata, nuvdata, otherdata, two=False, sel=None, **kwargs):
    """
    Plot log(flux^obs / flux^syn,0) vs. A_V + dA_V/2. Includes running median.
    """

    x = otherdata['avdav']
    z = np.log10(otherdata['sSFR'])

    y0 = (fuvdata['magobs'] - nuvdata['magobs']) - (fuvdata['magmodint'] - nuvdata['magmodint'])
    y1 = np.log10(fuvdata['fluxobs'] / fuvdata['fluxmodint'])
    y2 = np.log10(nuvdata['fluxobs'] / fuvdata['fluxmodint'])

    if sel is not None:
        x, z = x[sel], z[sel]
        y0, y1, y2 = y0[sel], y1[sel], y2[sel]

    this_x, this_z = x.flatten(), z.flatten()
    this_y0, this_y1, this_y2 = y0.flatten(), y1.flatten(), y2.flatten()

    xlim = [-0.05, 1.55]
    ylim0 = [-3, 3]
    ylim = [-2.95, 1.2]
    zlim = [-14, -10]

    xlabel = r'$A_V + \frac{1}{2} dA_V$'
    ylabel0 = (r'$(m_{\textrm{\small FUV}}-m_{\textrm{\small NUV}})_{\textrm{\small obs}} - (m_{\textrm{\small FUV}}-m_{\textrm{\small NUV}})_{\textrm{\small syn,0}}$')
    ylabel1 = (r'$\log \Bigg($' + fuvfluxobslab + '/' +
                  fuvfluxmodintlab + '$\Bigg)$')
    ylabel2 = (r'$\log \Bigg($' + nuvfluxobslab + '/' +
                  nuvfluxmodintlab + '$\Bigg)$')

    xlabels = [xlabel, xlabel, xlabel]
    ylabels = [ylabel0, ylabel1, ylabel2]

    zticks = np.linspace(zlim[0], zlim[-1], 5)
    cblabel = r'$\textrm{SFR}/\textrm{M}_{\star}$'
    extend='both'

    if kwargs['other']:
        func = 'median'
        cnorm = mcolors.Normalize(vmin=zlim[0], vmax=zlim[-1])
        fmt = None
        zlabel = cblabel
        extend = 'neither'
    else:
        # density of points
        func = 'count'
        zticks = [1, 2, 5, 10, 20, 50]
        vmax = zticks[-1]
        cnorm = mcolors.LogNorm(vmin=1, vmax=vmax)
        fmt = 'log'
        zlabel = 'Number of Regions'
        extend = 'max'

    hist_kwargs0 = {'func': func, 'bins': bins, 'xlim': xlim,
                   'ylim': ylim0, 'cnorm': cnorm}
    hist_kwargs1 = {'func': func, 'bins': bins, 'xlim': xlim,
                   'ylim': ylim, 'cnorm': cnorm}

    hist_kwargs = [hist_kwargs0, hist_kwargs1, hist_kwargs1]
    this_y = [this_y0, this_y1, this_y2]
    xlims, ylims = [xlim, xlim, xlim], [ylim0, ylim, ylim]

    #laws = [attenuation.cardelli, attenuation.calzetti, attenuation.smc]
    laws = [attenuation.conroy]
    #plot_laws = [('MW', '3.1', '1.0'), ('Calz', '4.05', '0.0'), ('SMC', '3.1', '0.0')]
    plot_laws = [('C10', '2.94', '0.68'), ('C10', '3.01', '0.63'), ('C10', '3.14', '0.63'), ('C10', '3.32', '0.71'), ('C10', '3.31', '0.66')]
    plot_laws = plot_laws[3:]
    ## [all, sfr>1e-5, sfr>1e-4, avdav>1.2, avdav>1.0]
    ## [blue, orange, green, red, cyanp]
    lawnames = list(np.array(plot_laws)[:,0])
    Rvs = [float(r) for r in np.array(plot_laws)[:,1]]
    bumps = [float(r) for r in np.array(plot_laws)[:,2]]
    filters = ['galex_fuv', 'galex_nuv']

    color = ['black']
    #color = ['Blue', 'Purple', 'darkorange']
    ptype = ['color', 'flux', 'flux']
    bands = [None, 'fuv', 'nuv']

    cmap = plt.cm.Greys_r
    cmap.set_bad('white')

    imlist, cnormlist = [], []

    fig, (ax0, ax1, ax2) = plt.subplots(1, 3, figsize=(12,4))
    ax_list = [ax0, ax1, ax2]

    for i in range(len(this_y)):
        im, cnorm, bindata = make_2dhist_func(ax_list[i], this_x, this_y[i], this_z, cmap=cmap, **hist_kwargs[i])
        imlist.append(im)
        cnormlist.append(cnorm)

        med_dust = running_median(this_x[np.isfinite(this_x)], this_y[i][np.isfinite(this_y[i])], ax_list[i], total_bins=8, min=0.2, max=1.5)

        plot_extcurve(ax_list[i], plot_type=ptype[i], laws=laws, lawnames=lawnames, filters=filters, plot_laws=plot_laws, Rvs=Rvs, bumps=bumps, lw=2, colors=color, band=bands[i])

    for i, ax in enumerate(ax_list):
        draw_grid(ax=ax)
        ax.set_xlabel(xlabels[i], fontsize=AXISLABELSIZE)
        ax.set_ylabel(ylabels[i], fontsize=AXISLABELSIZE)

        ax.set_xlim(xlims[i])
        ax.set_ylim(ylims[i])
        ax.tick_params(axis='both', labelsize=14)

    plt.subplots_adjust(wspace=0.4, right=0.98, top=0.9, bottom=0.1)

    create_cb(fig, ax_list, imlist, [zticks]*3, cnormlist, label=[zlabel]*3,
              cbw=0.03, orientation='horizontal', pad=-40, fmt='linear',
              extend=extend)

    plotname = 'm31_law_on_data.'
    if kwargs['other']:
        plotname = plotname.replace('_density.', 'avdav.')
    plotname = os.path.join(_PLOT_DIR, plotname) + plot_kwargs['format']
    print plotname

    if kwargs['save']:
        plt.savefig(plotname, **plot_kwargs)
    else:
        plt.show()

if __name__ == '__main__':
    sns.reset_orig()
    args = get_args()
    res = args.res
    dust_curve = args.dust_curve

    kwargs = {'other': args.other, 'save': args.save, 'vertical': True}
    plot_kwargs = {'dpi':300, 'bbox_inches':'tight', 'format':'pdf'}

    if os.environ['PATH'][1:6] == 'astro':
        _TOP_DIR = '/astro/store/phat/arlewis/'
    else:
        _TOP_DIR = '/Users/alexialewis/research/PHAT/'

    _DATA_DIR = os.path.join(_TOP_DIR, 'maps', 'analysis')
    _WORK_DIR = os.path.join(_TOP_DIR, 'dustvar')
    _PLOT_DIR = os.path.join(_WORK_DIR, 'plots')

    CBARTICKSIZE, AXISLABELSIZE, PLOTTEXTSIZE = 12, 18, 16
    M31_DM = 24.47

    sfr100lab = r'\textbf{$\langle\mathrm{SFR}\rangle_{100}$}'
    fuvfluxobslab = r'\textbf{$f_\mathrm{FUV}^\mathrm{obs}$}'
    fuvfluxmodredlab = r'\textbf{$f_\mathrm{FUV}^\mathrm{syn}$}'
    fuvfluxmodintlab = r'\textbf{$f_\mathrm{FUV}^\mathrm{syn,0}$}'

    nuvfluxobslab = r'\textbf{$f_\mathrm{NUV}^\mathrm{obs}$}'
    nuvfluxmodredlab = r'\textbf{$f_\mathrm{NUV}^\mathrm{syn}$}'
    nuvfluxmodintlab = r'\textbf{$f_\mathrm{NUV}^\mathrm{syn,0}$}'
    matchdustlab = r'$A_V + dA_V/2$'

    cmap, cmap2, cmap3, cmap4, cmap_resid = set_colormaps()
    origin = 'lower'
    aspect = 'auto'
    bins = 75
    interpolation='nearest'#none'


    ## gather data ##
    ## ----------- ##

    fuvdata, nuvdata, otherdata = compile_data.gather_map_data(res, dust_curve, sfh=args.sfh)
    sfhcube, sfhcube_upper, sfhcube_lower,sfhhdr = compile_data.gather_sfh(res)


    ## make figures ##
    ## ------------ ##
    #fig_att_curves(tage=0.0, **kwargs)   ##fig1
    #fig_fluxratio_av(fuvdata, nuvdata, otherdata, two=True, **kwargs)  ##fig2
    #fig_compare_rv_fb()  ## fig3
    #fig_region_triangles(otherdata, **kwargs)
    #fig_sigma_param_distributions(otherdata, **kwargs)
    fig_param_distributions(otherdata, **kwargs)
    #fig_boxplot(otherdata, first=False, **kwargs)
    #fig_ensemble_triangles(infile='/Users/alexialewis/research/PHAT/dustvar/sampler_independent/final_sampler_rv_fbump.h5', **kwargs)
    #fig_att_curves(tage=0.0, mine=True, **kwargs)

    sfrsel = otherdata['sfr100'] > 1e-5
    #fig_fluxratio_av(fuvdata, nuvdata, otherdata, two=True, sel=sfrsel, **kwargs)

    #cardelli_curves(tage=0.0, **kwargs)
    #conroy_curves(tage=0.0, **kwargs)
    #m31_dustlaw_on_data(fuvdata, nuvdata, otherdata, two=False, sel=None, **kwargs)


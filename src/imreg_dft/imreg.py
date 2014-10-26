# -*- coding: utf-8 -*-
# imreg.py

# Copyright (c) 2014-?, Matěj Týč
# Copyright (c) 2011-2014, Christoph Gohlke
# Copyright (c) 2011-2014, The Regents of the University of California
# Produced at the Laboratory for Fluorescence Dynamics
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
# * Neither the name of the copyright holders nor the names of any
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
FFT based image registration. --- main functions
"""

from __future__ import division, print_function

import math

import numpy as np
import numpy.fft as fft

import imreg_dft.utils as utils

try:
    import scipy.ndimage as ndi
    import scipy.ndimage.interpolation as ndii
except ImportError:
    import ndimage as ndi
    import ndimage.interpolation as ndii

__all__ = ['translation', 'similarity']


EXPO = 'inf'
#EXPO = 10


def _calc_cog(array, exponent):

    # When using an integer exponent for _calc_cog, it is good to have the
    # neutral rotation/scale in the center rather near the edges
    sarray = fft.fftshift(array)

    #import pylab as pyl
    #pyl.figure(); pyl.imshow(array); pyl.show()

    ret = None
    if exponent == "inf":
        amax = np.argmax(sarray)
        ret = list(np.unravel_index(amax, sarray.shape))
    else:
        col = np.arange(sarray.shape[0])[:, np.newaxis]
        row = np.arange(sarray.shape[1])[np.newaxis, :]

        arr2 = sarray ** exponent
        arrsum = arr2.sum()
        arrprody = np.sum(arr2 * col) / arrsum
        arrprodx = np.sum(arr2 * row) / arrsum
        ret = [arrprody, arrprodx]

    # Compensation of the fftshift
    ret[0] = (ret[0] + sarray.shape[0] / 2) % sarray.shape[0]
    ret[1] = (ret[1] + sarray.shape[1] / 2) % sarray.shape[1]
    return ret


def _getAngScale(ims):
    shape = ims[0].shape
    #import pylab as pyl
    #pyl.figure(); pyl.imshow(ims[1]); pyl.show()

    adfts = [fft.fftshift(abs(fft.fft2(im))) for im in ims]
    """
    h = highpass(f0.shape)
    for adft in adfts:
        adft *= h
    del h
    """

    stuffs = [_logpolar(adft, shape[1]) for adft in adfts]
    log_base = _getLogBase(shape, shape[1])

    stuffs = [fft.fft2(stuff) for stuff in stuffs]
    r0 = abs(stuffs[0]) * abs(stuffs[1])
    ir = abs(fft.ifft2((stuffs[0] * stuffs[1].conjugate()) / r0))

    i0, i1 = _calc_cog(ir, EXPO)

    angle = -180.0 * i0 / ir.shape[0]
    scale = log_base ** i1

    if scale > 1.8:
        ir = abs(fft.ifft2((stuffs[1] * stuffs[0].conjugate()) / r0))
        i0, i1 = _calc_cog(ir, EXPO)
        angle = 180.0 * i0 / ir.shape[0]
        scale = 1.0 / (log_base ** i1)
        if scale > 1.8:
            raise ValueError("Images are not compatible. Scale change > 1.8")

    if angle < -90.0:
        angle += 180.0
    elif angle > 90.0:
        angle -= 180.0

    return 1.0 / scale, - angle


def similarity(im0, im1, numiter=1, order=3, filter_pcorr=0):
    """
    Return similarity transformed image im1 and transformation parameters.
    Transformation parameters are: isotropic scale factor, rotation angle (in
    degrees), and translation vector.

    A similarity transformation is an affine transformation with isotropic
    scale and without shear.

    .. note:: There are limitations

        * Scale change must be less than 1.8.
        * No subpixel precision.

    Args:
        im0 (2D numpy array): The first (template) image
        im1 (2D numpy array): The second image
        numiter (int): How many times to iterate when determining scale and
            rotation
        order (int): Order of approximation (when doing transformations). 1 =
            linear, 3 = cubic etc.
        filter_pcorr (int): Radius of a spectrum filter for translation
            detection
    """
    if im0.shape != im1.shape:
        raise ValueError("Images must have same shapes.")
    elif im0.ndim != 2:
        raise ValueError("Images must be 2-dimensional.")

    # We are going to iterate and precise scale and angle estimates
    scale = 1.0
    angle = 0.0
    im2 = im1

    for ii in range(numiter):
        newscale, newangle = _getAngScale([im0, im2])
        scale *= newscale
        angle += newangle

        bgval = utils.get_borderval(im1, 5)
        im2 = transform_img(im1, scale, angle, bgval=bgval, order=order)

    # now we can use pcorr to guess the translation
    tvec = translation(im2, im0, filter_pcorr)

    # don't know what it does, but it alters the scale a little bit
    #scale = (im1.shape[1] - 1) / (int(im1.shape[1] / scale) - 1)

    res = dict(
        scale=scale,
        angle=angle,
        tvec=tvec,
    )

    # correct parameters for ndimage's internal processing
    # Probably calculated for the case the tform center is 0, 0 (vs center of
    # the image)
    if angle > 0.0:
        d = int((int(im1.shape[1] / scale) * math.sin(math.radians(angle))))
        tvec = d + tvec[1], d + tvec[0]
    elif angle < 0.0:
        d = int((int(im1.shape[0] / scale) * math.sin(math.radians(angle))))
        tvec = d + tvec[1], d + tvec[0]

    im2 = transform_img_dict(im1, res, bgval, order)
    imask = transform_img_dict(np.ones_like(im1), res, 0, order)

    # Framing here = just blending the im2 with its BG according to the mask
    im2 = utils.frame_img(im2, imask, 10)

    res["timg"] = im2
    return res


def translation(im0, im1, filter_pcorr=0):
    """
    Return translation vector to register images.

    Args:
        im0 (2D numpy array): The first (template) image
        im1 (2D numpy array): The second image
        filter_pcorr (int): Radius of a spectrum filter for translation
            detection
    Returns:
        tuple: The translation vector (Y, X)
    """
    f0 = fft.fft2(im0)
    f1 = fft.fft2(im1)
    ir = abs(fft.ifft2((f0 * f1.conjugate()) / (abs(f0) * abs(f1))))
    if filter_pcorr > 0:
        ir = ndi.minimum_filter(ir, filter_pcorr)

    t0, t1 = np.unravel_index(np.argmax(ir), ir.shape)

    if t0 > f0.shape[0] // 2:
        t0 -= f0.shape[0]
    if t1 > f0.shape[1] // 2:
        t1 -= f0.shape[1]

    return (-t0, -t1)


def transform_img_dict(img, tdict, bgval=0, order=1, invert=False):
    scale = tdict["scale"]
    angle = tdict["angle"]
    tvec = np.array(tdict["tvec"])
    if invert:
        scale = 1.0 / scale
        angle *= -1
        tvec *= -1
    res = transform_img(img, scale, angle, tvec, bgval=bgval, order=order)
    return res


def transform_img(img, scale=1.0, angle=0.0, tvec=(0, 0), bgval=0, order=1):
    """
    Return translation vector to register images.

    Args:
        img (2D numpy array): What will be transformed
        scale (float): The scale factor (scale > 1.0 means zooming in)
        angle (float): Degrees of rotation (clock-wise)
        tvec (2-tuple): Pixel translation vector, Y and X component.
        bgval (float): Shade of the background (filling in some cases of
            rotation and/or scaling)
        order (int): Order of approximation (when doing transformations). 1 =
            linear, 3 = cubic etc.

    Returns:
        The transformed img, may have another i.e. (bigger) shape than
        the source.
    """
    dest0 = img.copy()
    if scale != 1.0:
        dest0 = ndii.zoom(dest0, scale, order=order, cval=bgval)
    if angle != 0.0:
        dest0 = ndii.rotate(dest0, angle, order=order, cval=bgval)

    if tvec[0] != 0 or tvec[1] != 0:
        dest0 = ndii.shift(dest0, tvec, order=order, cval=bgval)

    bg = np.zeros_like(img) + bgval
    dest = utils.embed_to(bg, dest0)

    return dest


def similarity_matrix(scale, angle, vector):
    """
    Return homogeneous transformation matrix from similarity parameters.

    Transformation parameters are: isotropic scale factor, rotation angle (in
    degrees), and translation vector (of size 2).

    The order of transformations is: scale, rotate, translate.

    """
    S = np.diag([scale, scale, 1.0])
    R = np.identity(3)
    angle = math.radians(angle)
    R[0, 0] = math.cos(angle)
    R[1, 1] = math.cos(angle)
    R[0, 1] = -math.sin(angle)
    R[1, 0] = math.sin(angle)
    T = np.identity(3)
    T[:2, 2] = vector
    return np.dot(T, np.dot(R, S))


def _getLogBase(shape, radii):
    center = shape[0] / 2, shape[1] / 2
    d = np.hypot(shape[0] - center[0], shape[1] - center[1])
    log_base = 10.0 ** (math.log10(d) / (radii))
    return log_base


def _logpolar(image, radii, angles=None):
    """Return log-polar transformed image and log base."""
    shape = image.shape
    center = shape[0] / 2, shape[1] / 2
    if angles is None:
        angles = shape[0]
    theta = np.empty((angles, radii), dtype=np.float64)
    theta.T[:] = -np.linspace(0, np.pi, angles, endpoint=False)
    log_base = _getLogBase(shape, radii)
    radius = np.empty_like(theta)
    radius[:] = np.power(log_base, np.arange(radii,
                                             dtype=np.float64)) - 1.0
    x = radius * np.sin(theta) + center[0]
    y = radius * np.cos(theta) + center[1]
    output = np.empty_like(x)
    ndii.map_coordinates(image, [x, y], output=output)
    return output


def logpolar(image, angles=None, radii=None):
    """Return log-polar transformed image and log base."""
    shape = image.shape
    center = shape[0] / 2, shape[1] / 2
    if angles is None:
        angles = shape[0]
    if radii is None:
        radii = shape[1]
    theta = np.empty((angles, radii), dtype=np.float64)
    theta.T[:] = -np.linspace(0, np.pi, angles, endpoint=False)
    d = np.hypot(shape[0] - center[0], shape[1] - center[1])
    log_base = 10.0 ** (math.log10(d) / (radii))
    radius = np.empty_like(theta)
    radius[:] = np.power(log_base, np.arange(radii,
                                             dtype=np.float64)) - 1.0
    x = radius * np.sin(theta) + center[0]
    y = radius * np.cos(theta) + center[1]
    output = np.empty_like(x)
    ndii.map_coordinates(image, [x, y], output=output)
    return output, log_base


def highpass(shape):
    """Return highpass filter to be multiplied with fourier transform."""
    x = np.outer(
        np.cos(np.linspace(- math.pi / 2., math.pi / 2., shape[0])),
        np.cos(np.linspace(- math.pi / 2., math.pi / 2., shape[1])))
    return (1.0 - x) * (2.0 - x)


def imread(fname, norm=True):
    """Return image data from img&hdr uint8 files."""
    with open(fname + '.hdr', 'r') as fh:
        hdr = fh.readlines()
    img = np.fromfile(fname + '.img', np.uint8, -1)
    img.shape = int(hdr[4].split()[-1]), int(hdr[3].split()[-1])
    if norm:
        img = img.astype(np.float64)
        img /= 255.0
    return img


def imshow(im0, im1, im2, im3=None, cmap=None, **kwargs):
    """Plot images using matplotlib."""
    from matplotlib import pyplot

    if cmap is None:
        cmap = 'coolwarm'
    if im3 is None:
        # To increase the contrast of the difference, we norm images according
        # to their near-maximums
        norm = np.percentile(im2, 95) / np.percentile(im0, 95)
        im3 = abs(im2 - im0 * norm)
    pyplot.subplot(221)
    pyplot.imshow(im0, cmap, **kwargs)
    pyplot.grid()
    pyplot.subplot(222)
    pyplot.imshow(im1, cmap, **kwargs)
    pyplot.subplot(223)
    pyplot.imshow(im3, cmap, **kwargs)
    pyplot.subplot(224)
    pyplot.imshow(im2, cmap, **kwargs)
    pyplot.grid()
    pyplot.show()

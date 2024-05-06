"""Test the creation of `InstrumentData` from raw SHEBA DABUL `Dataset`."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest

from sio_postdoc.access import DataSet
from sio_postdoc.engine import Dimensions, Scales, Units
from sio_postdoc.engine.transformation.context.service import TransformationContext
from sio_postdoc.engine.transformation.contracts import (
    EPOCH,
    Dimension,
    DType,
    InstrumentData,
    Variable,
)
from sio_postdoc.engine.transformation.strategies.raw.eureka.mmcr import EurekaMmcrRaw

DIRECTORY: str = "/tests/access/instrument/integration/netCDF4_files/"
FILENAME: str = "eurmmcrmerge.C1.c1.D2008-09-21T00-00-00.eureka_mmcr_test.nc"
PATH: Path = Path(os.getcwd() + DIRECTORY + FILENAME)


@pytest.fixture(scope="module")
def context() -> TransformationContext:
    context: TransformationContext = TransformationContext()
    context.strategy = EurekaMmcrRaw()
    return context


@pytest.fixture(scope="module")
def dataset() -> Generator[DataSet, None, None]:
    data: DataSet = DataSet(PATH)
    yield data
    data.close()


@pytest.fixture(scope="module")
def data(context, dataset) -> InstrumentData:
    return context.hydrate(dataset, PATH)


def test_init(context):
    assert isinstance(context, TransformationContext)
    assert isinstance(context.strategy, EurekaMmcrRaw)


def test_dimensions(data):
    assert len(data.dimensions) == 2


def test_time_dimension(data):
    assert data.dimensions["time"] == Dimension(name=Dimensions.TIME, size=6)


def test_level_dimension(data):
    assert data.dimensions["level"] == Dimension(name=Dimensions.LEVEL, size=3)


def test_variables(data):
    assert len(data.variables) == 6


def test_epoch_variable(data):
    var: Variable = data.variables["epoch"]
    assert len(var.dimensions) == 0
    assert var.dtype == DType.I4
    assert var.long_name == "Unix Epoch 1970 of Initial Timestamp"
    assert var.scale == Scales.ONE
    assert var.units == Units.SECONDS
    assert var.values == 1221955200
    assert EPOCH + timedelta(seconds=var.values) == datetime(
        2008, 9, 21, 0, 0, tzinfo=timezone.utc
    )


def test_mean_dopp_vel_variable(data):
    var: Variable = data.variables["mean_dopp_vel"]
    assert len(var.dimensions) == 2
    assert var.dimensions[0] == Dimension(name=Dimensions.TIME, size=6)
    assert var.dimensions[1] == Dimension(name=Dimensions.LEVEL, size=3)
    assert var.dtype == DType.I2
    assert var.long_name == "Mean Doppler Velocity"
    assert var.scale == Scales.THOUSAND
    assert var.units == Units.METERS_PER_SECOND
    assert var.values == (
        (-32768, -32768, -32768),
        (77, 69, 61),
        (-4057, -1847, 363),
        (-4111, -2629, -1148),
        (-4460, -1692, 1076),
        (-4284, -1676, 931),
    )


def test_offset_variable(data):
    var: Variable = data.variables["offset"]
    assert len(var.dimensions) == 1
    assert var.dimensions[0] == Dimension(name=Dimensions.TIME, size=6)
    assert var.dtype == DType.I4
    assert var.long_name == "Seconds Since Initial Timestamp"
    assert var.scale == Scales.ONE
    assert var.units == Units.SECONDS
    assert var.values == (0, 10, 20, 30, 40, 50)


def test_range_variable(data):
    var: Variable = data.variables["range"]
    assert len(var.dimensions) == 1
    assert var.dimensions[0] == Dimension(name=Dimensions.LEVEL, size=3)
    assert var.dtype == DType.U2
    assert var.long_name == "Return Range"
    assert var.scale == Scales.ONE
    assert var.units == Units.METERS
    assert var.values == (54, 97, 140)


def test_refl_variable(data):
    var: Variable = data.variables["refl"]
    assert len(var.dimensions) == 2
    assert var.dimensions[0] == Dimension(name=Dimensions.TIME, size=6)
    assert var.dimensions[1] == Dimension(name=Dimensions.LEVEL, size=3)
    assert var.dtype == DType.I2
    assert var.long_name == "Reflectivity"
    assert var.scale == Scales.HUNDRED
    assert var.units == Units.DBZ
    assert var.values == (
        (-32768, -32768, -32768),
        (-3438, -3730, -5072),
        (-4511, -4802, -6151),
        (-4540, -4831, -6183),
        (-4303, -4595, -5946),
        (-4400, -4688, -5924),
    )


def test_spec_width_variable(data):
    var: Variable = data.variables["spec_width"]
    assert len(var.dimensions) == 2
    assert var.dimensions[0] == Dimension(name=Dimensions.TIME, size=6)
    assert var.dimensions[1] == Dimension(name=Dimensions.LEVEL, size=3)
    assert var.dtype == DType.I2
    assert var.long_name == "Spectral Width"
    assert var.scale == Scales.THOUSAND
    assert var.units == Units.METERS_PER_SECOND
    assert var.values == (
        (-32768, -32768, -32768),
        (470, 300, 130),
        (593, 353, 113),
        (513, 296, 80),
        (1013, 552, 91),
        (727, 466, 205),
    )

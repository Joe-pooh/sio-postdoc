"""Observation Manager Module."""

import os
import pickle
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sio_postdoc.access import DataSet
from sio_postdoc.access.instrument.service import InstrumentAccess
from sio_postdoc.access.local.service import LocalAccess
from sio_postdoc.engine import Dimensions, DType, Scales, Units
from sio_postdoc.engine.filtering import Content
from sio_postdoc.engine.filtering.context import FilterContext
from sio_postdoc.engine.filtering.strategies import IndicesByDate, NamesByDate
from sio_postdoc.engine.formatting.service import FormattingContext
from sio_postdoc.engine.formatting.strategies import YYYYMMDDdothhmmss
from sio_postdoc.engine.transformation.context.service import TransformationContext
from sio_postdoc.engine.transformation.contracts import (
    DateTime,
    Dimension,
    Direction,
    InstrumentData,
    MaskCode,
    MaskRequest,
    Threshold,
    Variable,
    VerticalLayers,
    VerticalTransition,
)
from sio_postdoc.engine.transformation.service import TransformationEngine
from sio_postdoc.engine.transformation.strategies.base import (
    SECONDS_PER_DAY,
    TransformationStrategy,
)
from sio_postdoc.engine.transformation.strategies.daily.products.arscl import (
    ArsclKazr1Kollias,
)
from sio_postdoc.engine.transformation.strategies.daily.products.mplcmask import (
    MplCmaskMl,
)
from sio_postdoc.engine.transformation.strategies.daily.products.sonde import (
    InterpolatedSonde,
)
from sio_postdoc.engine.transformation.strategies.daily.sheba.dabul import (
    ShebaDabulDaily,
)
from sio_postdoc.engine.transformation.strategies.daily.sheba.mmcr import ShebaMmcrDaily
from sio_postdoc.engine.transformation.strategies.daily.utqiagvik.kazr import (
    UtqiagvikKazrDaily,
)
from sio_postdoc.engine.transformation.strategies.masks import Masks
from sio_postdoc.engine.transformation.strategies.raw.eureka.ahsrl import EurekaAhsrlRaw
from sio_postdoc.engine.transformation.strategies.raw.eureka.mmcr import EurekaMmcrRaw
from sio_postdoc.engine.transformation.strategies.raw.products.arscl import (
    ArsclKazr1KolliasRaw,
)
from sio_postdoc.engine.transformation.strategies.raw.products.mplcmask import (
    MplCmaskMlRaw,
)
from sio_postdoc.engine.transformation.strategies.raw.products.sonde import (
    InterpolatedSondeRaw,
)
from sio_postdoc.engine.transformation.strategies.raw.sheba.dabul import ShebaDabulRaw
from sio_postdoc.engine.transformation.strategies.raw.sheba.mmcr import ShebaMmcrRaw
from sio_postdoc.engine.transformation.strategies.raw.utqiagvik.kazr import (
    UtqiagvikKazrRaw,
)
from sio_postdoc.manager.observation.contracts import (
    DailyProductRequest,
    DailyRequest,
    Instrument,
    Observatory,
    ObservatoryRequest,
    Product,
)

OFFSETS: dict[str, int] = {"time": 15, "elevation": 45}
STEPS: dict[str, int] = {key: value * 2 for key, value in OFFSETS.items()}
MIN_ELEVATION: int = 500
MASK_TYPE: DType = DType.I1
ONE_HALF: float = 1 / 2
VERTICAL_RAIL: int = -10

PHASE_LIQUID = 5
PHASE_MIXED_LIQUID = 4
PHASE_MIXED = 3
PHASE_MIXED_ICE = 2
PHASE_ICE = 1

RAIN = 4
LIQUID = 3
MIXED = 2
ICE = 1

Mask = tuple[tuple[int, ...], ...]


class ObservationManager:
    """TODO: Docstring."""

    def __init__(self) -> None:
        """Initialize the `ObservationManager`."""
        self._instrument_access: InstrumentAccess = InstrumentAccess()
        self._filter_context: FilterContext = FilterContext()
        self._transformation_context: TransformationContext = TransformationContext()
        self._formatting_context: FormattingContext = FormattingContext()
        self._transformation_engine: TransformationEngine = TransformationEngine()
        self._local_access: LocalAccess = LocalAccess()

    @property
    def instrument_access(self) -> InstrumentAccess:
        """Return the private instrument access."""
        return self._instrument_access

    @property
    def filter_context(self) -> FilterContext:
        """Return the private filter context."""
        return self._filter_context

    @property
    def transformation_context(self) -> TransformationContext:
        """Return the private transformation context."""
        return self._transformation_context

    @property
    def transformation_engine(self) -> TransformationEngine:
        """Return the private transformation engine."""
        return self._transformation_engine

    @property
    def formatting_context(self) -> TransformationContext:
        """Return the private formatting context."""
        return self._formatting_context

    @property
    def local_access(self) -> TransformationContext:
        """Return the private local access."""
        return self._local_access

    def format_dir(self, directory: Path, suffix: str, year: str):
        """Format the directory using the current formatting context."""
        current: Content = self.local_access.list_files(directory, suffix)
        new: Content = tuple(
            file.parent
            / self.formatting_context.format(
                file.name,
                year,
                strategy=YYYYMMDDdothhmmss(),
            )
            for file in current
        )
        self.local_access.rename_files(current, new)

    def create_daily_files(self, request: DailyRequest) -> None:
        """Create daily files for a given instrument, observatory, month and year."""
        # Get a list of all the relevant blobs
        blobs: tuple[str, ...] = self.instrument_access.list_blobs(
            container=request.observatory.name.lower(),
            name_starts_with=f"{request.instrument.name.lower()}/raw/{request.year}/",
        )
        # Create a daily file for each day in the month
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: tuple[str, ...] = self.filter_context.apply(
                target,
                blobs,
                strategy=NamesByDate(),
            )
            if not selected:
                continue
            # Select the Strategy
            match (request.observatory, request.instrument):
                case (Observatory.EUREKA, Instrument.AHSRL):
                    strategy: TransformationStrategy = EurekaAhsrlRaw()
                case (Observatory.EUREKA, Instrument.MMCR):
                    strategy: TransformationStrategy = EurekaMmcrRaw()
                case (Observatory.SHEBA, Instrument.DABUL):
                    strategy: TransformationStrategy = ShebaDabulRaw()
                case (Observatory.SHEBA, Instrument.MMCR):
                    strategy: TransformationStrategy = ShebaMmcrRaw()
                case (Observatory.UTQIAGVIK, Instrument.KAZR):
                    strategy: TransformationStrategy = UtqiagvikKazrRaw()
            # Generate a InstrumentData for each DataSet corresponding to the target date
            results: tuple[InstrumentData, ...] = tuple(
                self._generate_data(
                    selected,
                    request,
                    strategy=strategy,
                )
            )
            if not results:
                continue
            # Filter so only the target date exists in a single instance of `InstrumentData`
            data: InstrumentData | None = self.filter_context.apply(
                target,
                results,
                strategy=IndicesByDate(),
            )
            if not data:
                continue
            # Serialize the data.
            filepath: Path = self.transformation_context.serialize(
                target, data, request
            )
            # Add to blob storage
            self.instrument_access.add_blob(
                name=request.observatory.name.lower(),
                path=filepath,
                directory=f"{request.instrument.name.lower()}/daily_30smplcmask1zwang/{request.year}/",
            )
            # Remove the file
            os.remove(filepath)

    def create_daily_product_files(self, request: DailyProductRequest) -> None:
        """Create daily files for a given instrument, observatory, month and year."""
        # Get a list of all the relevant blobs
        blobs: tuple[str, ...] = self.instrument_access.list_blobs(
            container=request.observatory.name.lower(),
            name_starts_with=f"{request.product.name.lower()}/raw/{request.year}/",
        )
        # Create a daily file for each day in the month
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: tuple[str, ...] = self.filter_context.apply(
                target,
                blobs,
                strategy=NamesByDate(),
            )
            if not selected:
                continue
            # Select the Strategy
            match (request.observatory, request.product):
                case (Observatory.UTQIAGVIK, Product.ARSCLKAZR1KOLLIAS):
                    strategy: TransformationStrategy = ArsclKazr1KolliasRaw()
                case (Observatory.UTQIAGVIK, Product.MPLCMASKML):
                    strategy: TransformationStrategy = MplCmaskMlRaw()
                case (Observatory.UTQIAGVIK, Product.INTERPOLATEDSONDE):
                    strategy: TransformationStrategy = InterpolatedSondeRaw()
            # Generate a InstrumentData for each DataSet corresponding to the target date
            results: tuple[InstrumentData, ...] = tuple(
                self._generate_data(
                    selected,
                    request,
                    strategy=strategy,
                )
            )
            if not results:
                continue
            # Filter so only the target date exists in a single instance of `InstrumentData`
            data: InstrumentData | None = self.filter_context.apply(
                target,
                results,
                strategy=IndicesByDate(),
            )
            if not data:
                continue
            # Serialize the data.
            filepath: Path = self.transformation_context.serialize(
                target, data, request
            )
            # Add to blob storage
            self.instrument_access.add_blob(
                name=request.observatory.name.lower(),
                path=filepath,
                directory=f"{request.product.name.lower()}/daily/{request.year}/",
            )
            # Remove the file
            os.remove(filepath)

    def create_daily_resampled_merged_files(self, request: ObservatoryRequest) -> None:
        """Create daily files for a given instrument, observatory, month and year."""
        # Get a list of all the relevant blobs
        products = ["arsclkazr1kollias", "mplcmaskml", "interpolatedsonde"]
        blobs: dict[str, tuple[str, ...]] = {
            product: self.instrument_access.list_blobs(
                container=request.observatory.name.lower(),
                name_starts_with=f"{product}/daily/{request.year}/",
            )
            for product in products
        }
        # Create a daily file for each day in the month
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: dict[str, tuple[str] | tuple] = {
                product: self.filter_context.apply(
                    target,
                    blobs[product],
                    strategy=NamesByDate(),
                    time=False,
                )
                for product in products
            }
            if not all(selected.values()):
                continue
            # Because you need to set the strategy, you need to go through each product
            frames = {}
            for product in products:
                # Select the Strategy
                match (request.observatory, product):
                    case (Observatory.UTQIAGVIK, "arsclkazr1kollias"):
                        strategy: TransformationStrategy = ArsclKazr1Kollias()
                        # with open("arscl_instrument_data.pkl", "rb") as file:
                        #     results = pickle.load(file)
                    case (Observatory.UTQIAGVIK, "mplcmaskml"):
                        strategy: TransformationStrategy = MplCmaskMl()
                        # with open("mplcmaskml_instrument_data.pkl", "rb") as file:
                        #     results = pickle.load(file)
                    case (Observatory.UTQIAGVIK, "interpolatedsonde"):
                        strategy: TransformationStrategy = InterpolatedSonde()
                        # with open(
                        #     "interpolatedsonde_instrument_data.pkl", "rb"
                        # ) as file:
                        #     results = pickle.load(file)
                # Generate a InstrumentData for each DataSet corresponding to the target date
                results: tuple[InstrumentData, ...] = tuple(
                    self._generate_data(
                        selected[product],
                        request,
                        strategy=strategy,
                    )
                )
                if not results:
                    continue
                # There is only one per day
                data: InstrumentData = results[0]
                if not data:
                    continue
                # Now that you have the instrument data, you want to construct the dataframes
                if product == "arsclkazr1kollias":
                    frames["radar_mask"] = pd.DataFrame(
                        data.variables["radar_mask"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                    frames["refl"] = pd.DataFrame(
                        data.variables["refl"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                    frames["mean_dopp_vel"] = pd.DataFrame(
                        data.variables["mean_dopp_vel"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                    frames["spec_width"] = pd.DataFrame(
                        data.variables["spec_width"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                    frames["spec_width"] = pd.DataFrame(
                        data.variables["spec_width"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                    frames["mwr_lwp"] = pd.DataFrame(
                        data.variables["mwr_lwp"].values,
                        index=data.variables["offset"].values,
                        columns=["mwr_lwp"],
                    )
                elif product == "mplcmaskml":
                    frames["lidar_mask"] = pd.DataFrame(
                        data.variables["lidar_mask"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                    frames["depol"] = pd.DataFrame(
                        data.variables["depol"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                elif product == "interpolatedsonde":
                    frames["temp"] = pd.DataFrame(
                        data.variables["temp"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                    frames["rh"] = pd.DataFrame(
                        data.variables["rh"].values,
                        index=data.variables["offset"].values,
                        columns=data.variables["range"].values,
                    )
                # Now we have all of the dataframes
                if product == "arsclkazr1kollias":
                    # Radar Mask
                    flag_ = data.variables["radar_mask"].dtype.min
                    scale = data.variables["radar_mask"].scale.value
                    frames["radar_mask"].replace(flag_, 0, inplace=True)
                    frames["radar_mask"] = frames["radar_mask"] / scale
                    frames["radar_mask"].replace(2, 1, inplace=True)
                    frames["radar_mask"] = self._reformat(
                        frames["radar_mask"], method="mode"
                    )
                    # Reflectivity
                    flag_ = data.variables["refl"].dtype.min
                    scale = data.variables["refl"].scale.value
                    frames["refl"].replace(flag_, np.nan, inplace=True)
                    frames["refl"] = frames["refl"] / scale
                    frames["refl"] = self._reformat(
                        frames["refl"],
                        method="mean",
                    )
                    frames["refl"][frames["radar_mask"] == 0] = np.nan
                    # Mean Doppler Velocity
                    flag_ = data.variables["mean_dopp_vel"].dtype.min
                    scale = data.variables["mean_dopp_vel"].scale.value
                    frames["mean_dopp_vel"].replace(flag_, np.nan, inplace=True)
                    frames["mean_dopp_vel"] = frames["mean_dopp_vel"] / scale
                    frames["mean_dopp_vel"] = self._reformat(
                        frames["mean_dopp_vel"],
                        method="mean",
                    )
                    frames["mean_dopp_vel"][frames["radar_mask"] == 0] = np.nan
                    # Spectral Width
                    flag_ = data.variables["spec_width"].dtype.min
                    scale = data.variables["spec_width"].scale.value
                    frames["spec_width"].replace(flag_, np.nan, inplace=True)
                    frames["spec_width"] = frames["spec_width"] / scale
                    frames["spec_width"] = self._reformat(
                        frames["spec_width"],
                        method="mean",
                    )
                    frames["spec_width"][frames["radar_mask"] == 0] = np.nan
                    # MWR LWP
                    flag_ = data.variables["mwr_lwp"].dtype.min
                    scale = data.variables["mwr_lwp"].scale.value
                    frames["mwr_lwp"].replace(flag_, np.nan, inplace=True)
                    frames["mwr_lwp"] = frames["mwr_lwp"] / scale
                    frames["mwr_lwp"] = self._reformat_1D(
                        frames["mwr_lwp"],
                        method="mean",
                    )
                elif product == "mplcmaskml":
                    # Lidar Mask
                    flag_ = data.variables["lidar_mask"].dtype.min
                    scale = data.variables["lidar_mask"].scale.value
                    frames["lidar_mask"].replace(flag_, 0, inplace=True)
                    frames["lidar_mask"] = frames["lidar_mask"] / scale
                    frames["lidar_mask"] = self._reformat(
                        frames["lidar_mask"], method="mode"
                    )
                    # Depolarization Ratio
                    flag_ = data.variables["depol"].dtype.min
                    scale = data.variables["depol"].scale.value
                    frames["depol"].replace(flag_, np.nan, inplace=True)
                    frames["depol"] = frames["depol"] / scale
                    frames["depol"] = self._reformat(
                        frames["depol"],
                        method="mean",
                    )
                    frames["depol"][frames["lidar_mask"] == 0] = np.nan
                elif product == "interpolatedsonde":
                    # Temperature
                    flag_ = data.variables["temp"].dtype.min
                    scale = data.variables["temp"].scale.value
                    frames["temp"].replace(flag_, np.nan, inplace=True)
                    frames["temp"] = frames["temp"] / scale
                    frames["temp"] = self._reformat(
                        frames["temp"],
                        method="mean",
                    )
                    # Relative Humidity
                    flag_ = data.variables["rh"].dtype.min
                    scale = data.variables["rh"].scale.value
                    frames["rh"].replace(flag_, np.nan, inplace=True)
                    frames["rh"] = frames["rh"] / scale
                    frames["rh"] = self._reformat(
                        frames["rh"],
                        method="mean",
                    )
            # Now we should have all of the reformatted data that we want to seralize
            # pickle the frames.
            filepath: Path = Path.cwd() / (
                f"D{target.year}"
                f"-{str(target.month).zfill(2)}"
                f"-{str(target.day).zfill(2)}"
                f"-{request.observatory.name.lower()}"
                "-resampled_frames"
                ".pkl"
            )
            with open(filepath, "wb") as file:
                pickle.dump(frames, file)
            # Add to blob storage
            self.instrument_access.add_blob(
                name=request.observatory.name.lower(),
                path=filepath,
                directory=f"resampled_frames/daily/{request.year}/",
            )
            # Remove the file
            os.remove(filepath)

    def create_daily_layers_and_phases(self, request: ObservatoryRequest) -> None:
        """Create daily files for a given instrument, observatory, month and year."""
        # Get a list of all the relevant blobs
        blobs: tuple[str, ...] = self.instrument_access.list_blobs(
            container=request.observatory.name.lower(),
            name_starts_with=f"resampled_frames/daily/{request.year}/",
        )
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: tuple[str, ...] = self.filter_context.apply(
                target,
                blobs,
                strategy=NamesByDate(),
                time=False,
            )
            if not selected:
                continue
            # Now that I have the blob (pkl) I need to download it
            # There is only one in each selected
            name: str = selected[0]
            filename = self.instrument_access.download_blob(
                container=request.observatory.name.lower(),
                name=name,
            )
            # Rather than yield the instrument data, you just want to unpickle the dataframes
            filepath: Path = Path.cwd() / filename
            with open(filepath, "rb") as file:
                frames = pickle.load(file)
            os.remove(filepath)
            # Now we should have the combined frames
            steps: dict[str, pd.DataFrame] = {}
            # Step 1 ------------------------------------------------------------------------
            steps["1"] = frames["depol"].copy(deep=True)
            steps["1"][frames["depol"] < 0.1] = LIQUID
            steps["1"][0.1 <= frames["depol"]] = ICE
            # Step 2 ------------------------------------------------------------------------
            # Make a copy
            steps["2"] = steps["1"].copy(deep=True)
            # Classify mixed-phase
            steps["2"][
                (steps["1"] == LIQUID)  # Lidar detected liquid
                & (frames["temp"] < 0)  # Below freezing
                & (-17 <= frames["refl"])  # High reflectivity
            ] = MIXED
            steps["2"][
                (steps["1"] == LIQUID)  # Lidar detected liquid
                & (frames["temp"] < 0)  # Below freezing
                & (1 <= frames["mean_dopp_vel"])  # High velocity
            ] = MIXED
            # Classify Rain
            steps["2"][
                (steps["1"] == LIQUID)  # Lidar detected liquid
                & (0 <= frames["temp"])  # Above freezing
                & (-17 <= frames["refl"])  # High reflectivity
            ] = RAIN
            steps["2"][
                (steps["1"] == LIQUID)  # Lidar detected liquid
                & (0 <= frames["temp"])  # Above freezing
                & (1 <= frames["mean_dopp_vel"])  # High velocity
            ] = RAIN
            # Step 3 ------------------------------------------------------------------------
            # Make a copy
            steps["3"] = steps["2"].copy(deep=True)
            # Reclassify snow and rain based on reflectivity greater than 5
            steps["3"][
                (frames["temp"] < 0)  # Below freezing
                & (5 <= frames["refl"])  # High reflectivity
            ] = ICE
            steps["3"][
                (0 <= frames["temp"])  # Above freezing
                & (5 <= frames["refl"])  # High reflectivity
            ] = RAIN
            # Reclassify rain when velocity is greater than 2.5 and temperature is above freezing
            steps["3"][
                (0 <= frames["temp"])  # Above freezing
                & (2.5 <= frames["mean_dopp_vel"])  # High velocity
            ] = RAIN
            # Step 4 ------------------------------------------------------------------------
            # Make a copy for step 4
            steps["4"] = steps["3"].copy(deep=True)
            # First set all of the values that are in the mask to rain
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (0 <= frames["temp"])  # Above freezing
                & (frames["radar_mask"] == 1)  # Pixels viewed by radar
            ] = RAIN
            # Now cut in with drizzle
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (0 <= frames["temp"])  # Above freezing
                & (frames["refl"] < 5)  # Mid reflectivity
                & (frames["mean_dopp_vel"] < 2.5)  # Mid velocity
            ] = RAIN
            # Finally cut in with liquid
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (0 <= frames["temp"])  # Above freezing
                & (frames["refl"] < -17)  # Low reflectivity
                & (frames["mean_dopp_vel"] < 1)  # Low velocity
            ] = LIQUID
            # Differentiate between snow and ice below freezing using reflectivity at narrow widths.
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
                & (frames["spec_width"] < 0.4)  # Narrow widths
                & (frames["refl"] < 5)  # Low reflecitvity
            ] = ICE
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
                & (frames["spec_width"] < 0.4)  # Narrow widths
                & (5 <= frames["refl"])  # High reflecitvity
            ] = ICE
            # Differentiate between liquid, mixed-phase, and snow below freezing using reflectivity at elevated widths.
            # First set everything to snow
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
                & (0.4 <= frames["spec_width"])  # Extended widths
            ] = ICE
            # Now cut in with mixed-phase
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
                & (0.4 <= frames["spec_width"])  # Extended widths
                & (frames["refl"] < 5)  # Mid reflecitvity
            ] = MIXED
            # Finally cut in with liquid
            steps["4"][
                (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
                & (0.4 <= frames["spec_width"])  # Extended widths
                & (frames["refl"] < -17)  # Low reflecitvity
                & (frames["mean_dopp_vel"] < 1)  # Low velocity
            ] = LIQUID
            # Lidar Occulation Zone
            # Start with a dataframe of all zeros
            # NOTE: the Occulation Zone is Step -1
            steps["occulation_zone"] = steps["4"].copy(deep=True)
            for col in steps["occulation_zone"].columns:
                steps["occulation_zone"][col].values[:] = 0
            # Find the radar tops
            steps["radar_tops"] = steps["4"].copy(deep=True)
            steps["radar_tops"].iloc[:, :-1] = (
                frames["radar_mask"].iloc[:, :-1].values
                - frames["radar_mask"].iloc[:, 1:].values
            )
            steps["radar_tops"].iloc[:, -1] = 0
            # Find the lidar tops
            steps["lidar_tops"] = steps["4"].copy(deep=True)
            steps["lidar_tops"].iloc[:, :-1] = (
                frames["lidar_mask"].iloc[:, :-1].values
                - frames["lidar_mask"].iloc[:, 1:].values
            )
            steps["lidar_tops"].iloc[:, -1] = 0
            # Find Lidar Occulation Levels and Radar Tops
            lidar_occulation_levels = steps["lidar_tops"].T.apply(
                lambda series: series[series == 1].index.max()
            )
            radar_tops_levels = steps["radar_tops"].T.apply(
                lambda series: series[series == 1].index.tolist()
            )
            for i, t in enumerate(steps["lidar_tops"].index):
                for radar_top in radar_tops_levels[t]:
                    base = lidar_occulation_levels[t]
                    if 0 <= radar_top - base <= 750:
                        # then set the values in the given location between these values to 1
                        steps["occulation_zone"].loc[t, base:radar_top] = 1
            # Use occulation zone to Differentiate between liquid, mixed-phase, and snow below freezing using reflectivity regardless of spectral width.
            # First set everything to snow
            steps["4"][
                (steps["occulation_zone"] == 1)  # In occulation zone
                & (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
            ] = ICE
            # Now cut in with mixed-phase
            steps["4"][
                (steps["occulation_zone"] == 1)  # In occulation zone
                & (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
                & (frames["refl"] < 5)  # Mid reflecitvity
            ] = MIXED
            # Finally cut in with liquid
            steps["4"][
                (steps["occulation_zone"] == 1)  # In occulation zone
                & (frames["lidar_mask"] == 0)  # Pixels not viewed by lidar
                & (frames["temp"] < 0)  # Below freezing
                & (frames["refl"] < -17)  # Low reflecitvity
                & (frames["mean_dopp_vel"] < 1)  # Low velocity
            ] = LIQUID
            # Step 5 ------------------------------------------------------------------------
            # Absolute Temperature Rules
            # TODO: You are here
            # Make a copy for step 5
            steps["5"] = steps["4"].copy(deep=True)
            # Find all the locations where step 4 is in both of the masks is below -40
            # Below - 40 you can only have ice or snow and you can differentiate show using reflectivity > 5
            steps["5"][
                (frames["temp"] < -40)  # Below homogeneous freezing
                & (steps["5"] == RAIN)
            ] = ICE
            steps["5"][
                (frames["temp"] < -40)  # Below homogeneous freezing
                & (steps["5"] == LIQUID)
            ] = ICE
            steps["5"][
                (frames["temp"] < -40)  # Below homogeneous freezing
                & (steps["5"] == MIXED)
            ] = ICE
            # Above zero you can only have rain, drizzle, or liquid.
            # You can differentiate these with doppler velocity and reflectivity.
            steps["5"][
                (0 <= frames["temp"]) & (steps["5"] == MIXED)  # Above freezing
            ] = LIQUID
            steps["5"][
                (0 <= frames["temp"]) & (steps["5"] == ICE)  # Above freezing
            ] = LIQUID
            # Step 6 ------------------------------------------------------------------------
            # Make a copy for step 6
            # steps["6"] = steps["5"].copy(deep=True)
            # Identify layers and phases
            # SKIP Step 6 and 7 for now...
            # layers_and_phases = steps["6"].T.apply(self._identify_layers_and_phases)
            # # Add liquid if the lwp is greater than 25 but no liquid in the column
            # for row in frames["mwr_lwp"].index:
            #     lwp = frames["mwr_lwp"].loc[row, "mwr_lwp"]
            #     if 25 <= lwp:
            #         # Has a liquid layer been identified?
            #         # NOTE: This is where you're at and it is difficult to see right now
            #         try:
            #             max_phase = max(
            #                 max(layer["phases"]) for layer in layers_and_phases[row]
            #             )
            #         except ValueError:
            #             max_phase = 0
            #         if max_phase < 3:
            #             # Then a liquid must be specified.
            #             lidar_tops = steps["lidar_tops"].loc[row, :]
            #             base = lidar_tops[lidar_tops == -1].index.min() - 45
            #             if np.isnan(base):
            #                 # Then use the radar base
            #                 radar_tops = steps["radar_tops"].loc[row, :]
            #                 base = radar_tops[radar_tops == -1].index.min() - 45
            #                 if np.isnan(base):
            #                     continue
            #             # Now we have a base
            #             # Is there a top within 500 m
            #             measured_top = [
            #                 i["top"]
            #                 for i in layers_and_phases[row]
            #                 if 0 <= i["top"] - base < 500
            #             ]
            #             if measured_top:
            #                 top = measured_top[0]
            #             else:
            #                 # We need to calculate the thickness
            #                 thickness = lwp / 0.2
            #                 top = base + thickness + 45
            #             # Now that we have a base and a top
            #             # We want to classify everything above the base and below the top as liquid
            #             steps["6"].loc[
            #                 row,
            #                 (base < steps["6"].columns) & (steps["6"].columns < top),
            #             ] = LIQUID
            #     elif lwp < 0:
            #         # Then all liquid containing elements below freezing are set to ice
            #         steps["6"].loc[
            #             row,
            #             (frames["temp"].loc[row, :] < 0)
            #             & (MIXED <= steps["6"].loc[row, :]),
            #         ] = ICE
            # Now that we are done with all of the steps
            # pickle the frames
            filepath: Path = Path.cwd() / (
                f"D{target.year}"
                f"-{str(target.month).zfill(2)}"
                f"-{str(target.day).zfill(2)}"
                f"-{request.observatory.name.lower()}"
                "-mask_steps"
                ".pkl"
            )
            with open(filepath, "wb") as file:
                pickle.dump(steps, file)
            # Add to blob storage
            self.instrument_access.add_blob(
                name=request.observatory.name.lower(),
                path=filepath,
                directory=f"mask_steps/daily/{request.year}/",
            )
            # Remove the file
            os.remove(filepath)

    def create_daily_masks(self, request: DailyRequest) -> None:
        """Create daily files for a given instrument, observatory, month and year."""
        # Get a list of all the relevant blobs
        blobs: tuple[str, ...] = self.instrument_access.list_blobs(
            container=request.observatory.name.lower(),
            name_starts_with=f"{request.instrument.name.lower()}/daily/{request.year}/",
        )
        # Create a daily file for each day in the month
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: tuple[str, ...] = self.filter_context.apply(
                target,
                blobs,
                strategy=NamesByDate(),
                time=False,
            )
            if not selected:
                continue
            # Set the strategy
            strategy: TransformationStrategy
            match (request.observatory, request.instrument):
                case (Observatory.SHEBA, Instrument.DABUL):
                    strategy = ShebaDabulDaily()
                case (Observatory.SHEBA, Instrument.MMCR):
                    strategy = ShebaMmcrDaily()
                case (Observatory.EUREKA, Instrument.MMCR):
                    # NOTE: You can use the single MmcrDaily Strategy
                    # TODO: Rename this from ShebaMmcrDaily to MmcrDaily
                    strategy = ShebaMmcrDaily()
            # Generate a InstrumentData for each DataSet corresponding to the target date
            results: tuple[InstrumentData, ...] = tuple(
                self._generate_data(
                    selected,
                    request,
                    strategy=strategy,
                )
            )
            if not results:
                continue
            # Filter so only the target date exists in a single instance of `InstrumentData`
            data: InstrumentData = results[0]
            if not data:
                continue
            # Set the Window and threshold
            length: int = 3
            scale: int = 100
            dtype: DType = DType.I2
            match (request.observatory, request.instrument):
                case (Observatory.EUREKA, Instrument.MMCR):
                    height: int = 2
                    long_name: str = "Radar Cloud Mask"
                    name: str = "refl"
                    threshold: Threshold = Threshold(
                        value=10, direction=Direction.LESS_THAN
                    )
                case (Observatory.SHEBA, Instrument.DABUL):
                    height: int = 3
                    long_name: str = "Lidar Cloud Mask"
                    name: str = "far_par"
                    threshold: Threshold = Threshold(
                        value=55, direction=Direction.GREATER_THAN
                    )
                case (Observatory.SHEBA, Instrument.MMCR):
                    height: int = 2
                    long_name: str = "Radar Cloud Mask"
                    name: str = "refl"
                    threshold: Threshold = Threshold(
                        value=10, direction=Direction.LESS_THAN
                    )
            # Now you want to apply the mask.
            mask_request: MaskRequest = MaskRequest(
                values=data.variables[name].values,
                length=length,
                height=height,
                threshold=threshold,
                scale=scale,
                dtype=dtype,
            )
            mask: Mask = self.transformation_engine.get_mask(mask_request)
            data.variables["cloud_mask"] = Variable(
                dtype=MASK_TYPE,
                long_name=long_name,
                scale=Scales.ONE,
                units=Units.NONE,
                dimensions=(
                    Dimension(
                        name=Dimensions.TIME, size=len(data.variables[name].values)
                    ),
                    Dimension(
                        name=Dimensions.LEVEL, size=len(data.variables[name].values[0])
                    ),
                ),
                values=mask,
            )
            # Serialize the data.
            filepath: Path = self.transformation_context.serialize(
                target, data, request
            )
            # Add to blob storage
            self.instrument_access.add_blob(
                name=request.observatory.name.lower(),
                path=filepath,
                directory=f"{request.instrument.name.lower()}/masks/{request.year}/threshold_{threshold.value}/",
            )
            # Remove the file
            os.remove(filepath)

    def merge_daily_masks(self, request: ObservatoryRequest) -> None:
        """Merge daily masks for a given observatory, month and year.

        TODO: The logic belogs in an engine (Transformation).
        """
        # Get a list of all the relevant blobs
        instruments: dict[str, Instrument] = {}
        match request.observatory:
            case Observatory.SHEBA:
                instruments["lidar"] = Instrument.DABUL
                instruments["radar"] = Instrument.MMCR
        blobs: dict[Instrument, tuple[str, ...]] = {
            instrument: self.instrument_access.list_blobs(
                container=request.observatory.name.lower(),
                name_starts_with=f"{instrument.name.lower()}/masks/{request.year}/",
            )
            for instrument in instruments.values()
        }
        # Merge the masks for each day in the month
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: dict[Instrument, tuple[str, ...]] = {
                instrument: self.filter_context.apply(
                    target,
                    blobs[instrument],
                    strategy=NamesByDate(),
                    time=False,
                )
                for instrument in instruments.values()
            }
            if not all(selected.values()):
                continue
            strategy: TransformationStrategy = Masks()
            # Generate a InstrumentData for each DataSet corresponding to the target date
            results: dict[Instrument, tuple[InstrumentData, ...]] = {
                instrument: tuple(
                    self._generate_data(
                        selected[instrument],
                        request,
                        strategy=strategy,
                    )
                )
                for instrument in instruments.values()
            }
            # NOTE: You can quickly skip to here by using the following.
            # with open("results.pkl", "rb") as file:
            #     results = pickle.load(file)
            if not all(results.values()):
                continue
            # There should only be one value in each result
            data: dict[Instrument, InstrumentData] = {
                instrument: results[instrument][0]
                for instrument in instruments.values()
            }
            # Convert to DataFrames for processing
            # NOTE: This could be done with a transformation strategy as well.
            # TODO: Use a transformation strategy here.
            dataframes: dict[Instrument, pd.DataFrame] = {
                instrument: pd.DataFrame(
                    instrument_data.variables["cloud_mask"].values,
                    index=instrument_data.variables["offset"].values,
                    columns=instrument_data.variables["range"].values,
                )
                for instrument, instrument_data in data.items()
            }
            # Set up the new merged mask
            max_elevation: int = min(df.columns.max() for df in dataframes.values())
            times: list[int] = list(range(0, SECONDS_PER_DAY + 1, STEPS["time"]))
            elevations: list[int] = list(
                range(0, max_elevation + 1, STEPS["elevation"])
            )
            mask: list[list[int]] = [[0 for _ in elevations] for _ in times]
            for i, time in enumerate(times):
                selected_times: dict[Instrument, list[bool]] = {
                    key: [
                        a and b
                        for a, b in zip(
                            time - OFFSETS["time"] <= df.index,
                            df.index < time + OFFSETS["time"],
                        )
                    ]
                    for key, df in dataframes.items()
                }
                for j, elevation in enumerate(elevations):
                    if elevation < MIN_ELEVATION:
                        continue
                    selected_elevations: dict[Instrument, list[bool]] = {}
                    values: dict[Instrument, pd.DataFrame] = {}
                    sizes: dict[Instrument, int] = {}
                    means: dict[Instrument, float] = {}
                    for inst, df in dataframes.items():
                        selected_elevations[inst] = [
                            a and b
                            for a, b in zip(
                                elevation - OFFSETS["elevation"] <= df.columns,
                                df.columns < elevation + OFFSETS["elevation"],
                            )
                        ]
                        values[inst] = df.iloc[
                            selected_times[inst], selected_elevations[inst]
                        ]
                        sizes[inst] = values[inst].size
                        means[inst] = values[inst].mean().mean()
                    # Now set the value of the flags
                    CLOUD = DType.I1.min
                    NO_CLOUD = DType.I1.min
                    if not any(sizes.values()):
                        mask[i][j] = -6  # Missing all data
                        continue
                    elif all(DType.I1.min in df.values for df in values.values()):
                        if not any(
                            ONE_HALF <= df.replace(DType.I1.min, 0).mean().mean()
                            for df in values.values()
                        ):
                            mask[i][j] = 0
                            continue
                        for instrument, df in values.items():
                            if ONE_HALF <= df.replace(DType.I1.min, 0).mean().mean():
                                match instrument:
                                    case (
                                        Instrument.AHSRL
                                        | Instrument.DABUL
                                        | Instrument.MPL
                                    ):
                                        # This is when the lidar is greater than 0.5 while the radar has flags
                                        mask[i][j] = 1
                                    case Instrument.MMCR:
                                        # This is when the radar is greater than 0.5 while the lidar has flags
                                        mask[i][j] = 2
                                break
                        continue
                    elif not all(sizes.values()):  # At least one is empty
                        for instrument, size in sizes.items():
                            if not size:
                                match instrument:
                                    case (
                                        Instrument.AHSRL
                                        | Instrument.DABUL
                                        | Instrument.MPL
                                    ):
                                        # Cloud detected by radar with EMPTY lidar signal
                                        CLOUD = 4
                                        # No cloud detected by radar with EMPTY lidar signal
                                        NO_CLOUD = -4
                                    case Instrument.MMCR:
                                        # Cloud detected by lidar with EMPTY radar signal
                                        CLOUD = 5
                                        # No cloud detected by lidar with EMPTY radar signal
                                        NO_CLOUD = -5
                                break
                    elif any(DType.I1.min in df.values for df in values.values()):
                        # The Flag is in at lease one
                        for instrument, df in values.items():
                            if DType.I1.min in df.values:
                                match instrument:
                                    case (
                                        Instrument.AHSRL
                                        | Instrument.DABUL
                                        | Instrument.MPL
                                    ):
                                        # Cloud detected by radar with both signals available
                                        CLOUD = 2
                                        # No cloud detected by radar with both signals available
                                        NO_CLOUD = -2
                                    case Instrument.MMCR:
                                        # Cloud detected by lidar with both signals available
                                        CLOUD = 1
                                        # No cloud detected by lidar with both signals available
                                        NO_CLOUD = -1
                                break
                    elif all(ONE_HALF <= i for i in means.values()):
                        # Then both of the signals say there is a cloud
                        mask[i][j] = 3
                        continue
                    elif any(ONE_HALF <= i for i in means.values()):
                        # Then only one is saying there is a value
                        for instrument, df in values.items():
                            if means[instrument] < ONE_HALF:
                                match instrument:
                                    case (
                                        Instrument.AHSRL
                                        | Instrument.DABUL
                                        | Instrument.MPL
                                    ):
                                        # Lidar less than 1/2 but not radar
                                        mask[i][j] = 2
                                    case Instrument.MMCR:
                                        # Radar less than 1/2 but not lidar
                                        mask[i][j] = 1
                                break
                        continue
                    else:  # all means are less than 0.5 (Clear by both)
                        mask[i][j] = -3
                        continue
                    mask[i][j] = (
                        CLOUD
                        if any(ONE_HALF <= v.mean().mean() for v in values.values())
                        else NO_CLOUD
                    )
            # NOTE: SPEED THINGS UP
            # with open("mask_list.pkl", "rb") as file:
            #     mask = pickle.load(file)
            mask: pd.DataFrame = pd.DataFrame(
                mask,
                index=times,
                columns=elevations,
            )
            # Now construct the instrument data that you can persist as a blob
            dimensions: dict[str, Dimension] = {
                "time": Dimension(name=Dimensions.TIME, size=len(times)),
                "level": Dimension(name=Dimensions.LEVEL, size=len(elevations)),
            }
            variables: dict[str, Variable] = {
                "epoch": Variable(
                    dimensions=(),
                    dtype=DType.I4,
                    long_name="Unix Epoch 1970 of Initial Timestamp",
                    scale=Scales.ONE,
                    units=Units.SECONDS,
                    values=DateTime(
                        year=target.year,
                        month=target.month,
                        day=target.day,
                        hour=0,
                        minute=0,
                        second=0,
                    ).unix,
                ),
                "offset": Variable(
                    dimensions=(dimensions["time"],),
                    dtype=DType.I4,
                    long_name="Seconds Since Initial Timestamp",
                    scale=Scales.ONE,
                    units=Units.SECONDS,
                    values=tuple(times),
                ),
                "range": Variable(
                    dimensions=(dimensions["level"],),
                    dtype=DType.U2,
                    long_name="Return Range",
                    scale=Scales.ONE,
                    units=Units.METERS,
                    values=tuple(elevations),
                ),
                "cloud_mask": Variable(
                    dimensions=(dimensions["time"], dimensions["level"]),
                    dtype=DType.I1,
                    long_name="Cloud Mask",
                    scale=Scales.ONE,
                    units=Units.NONE,
                    values=tuple(tuple(j for j in mask.loc[i][:]) for i in mask.index),
                ),
            }
            instrument_data: InstrumentData = InstrumentData(
                dimensions=dimensions, variables=variables
            )
            # Serialize the data.
            filepath: Path = self.transformation_context.serialize_mask(
                target,
                instrument_data,
                request,
            )
            # Add to blob storage
            self.instrument_access.add_blob(
                name=request.observatory.name.lower(),
                path=filepath,
                directory=f"combined_masks/{request.year}/",
            )
            # Remove the file
            os.remove(filepath)

    def extract_daily_extents(self, request: ObservatoryRequest) -> None:
        """Extract daily cloud extent from combined masks for a given observatory, month and year.

        TODO: The logic belogs in an engine (Transformation).
        """
        # Get a list of all the relevant blobs
        blobs: tuple[str, ...] = self.instrument_access.list_blobs(
            container=request.observatory.name.lower(),
            name_starts_with=f"combined_masks/{request.year}/",
        )
        # Extract the data for each day
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: tuple[str, ...] = self.filter_context.apply(
                target, blobs, strategy=NamesByDate(), time=False
            )
            if not selected:
                continue
            # Generate a InstrumentData of the Mask
            results: tuple[InstrumentData, ...] = tuple(
                self._generate_data(
                    selected,
                    request,
                    strategy=Masks(),
                )
            )
            if not results:
                continue
            # There should only be one value in the result
            data: InstrumentData = results[0]
            # Convert to DataFrames for processing
            # NOTE: This could be done with a transformation strategy as well.
            # TODO: Use a transformation strategy here.
            dataframe: pd.DataFrame = pd.DataFrame(
                data.variables["cloud_mask"].values,
                index=data.variables["offset"].values,
                columns=data.variables["range"].values,
            )
            # NOTE: This looks like an internal method.
            # NOTE: Or a method that belongs in the engine.
            base_time: datetime = datetime(
                target.year, target.month, target.day, tzinfo=timezone.utc
            )
            result: list[VerticalLayers] = []
            for i, offset in enumerate(dataframe.index):
                below: int = VERTICAL_RAIL
                bases: list[VerticalTransition] = []
                tops: list[VerticalTransition] = []
                for j, elevation in enumerate(dataframe.columns[:-1]):
                    if elevation < MIN_ELEVATION:
                        continue
                    current: int = int(dataframe.iloc[i, j])
                    above: int = int(dataframe.iloc[i, j + 1])
                    if below <= 0 < current:
                        bases.append(
                            VerticalTransition(
                                elevation=elevation - OFFSETS["elevation"],
                                code=MaskCode(bottom=below, top=current),
                            )
                        )
                    if above <= 0 < current:
                        tops.append(
                            VerticalTransition(
                                elevation=elevation + OFFSETS["elevation"],
                                code=MaskCode(bottom=current, top=above),
                            )
                        )
                    # But before moving on, set below to current
                    below = int(current)
                # Now, you're one away from the top
                current = dataframe.iloc[i, j + 1]
                if 0 < current:
                    tops.append(
                        VerticalTransition(
                            elevation=elevation + OFFSETS["elevation"],
                            code=MaskCode(bottom=current, top=VERTICAL_RAIL),
                        )
                    )
                    if below <= 0:
                        bases.append(
                            VerticalTransition(
                                elevation=elevation - OFFSETS["elevation"],
                                code=MaskCode(bottom=below, top=current),
                            )
                        )
                # Now that you are done with the time slice create VerticalLayers
                result.append(
                    VerticalLayers(
                        datetime=base_time + timedelta(seconds=offset),
                        bases=tuple(bases),
                        tops=tuple(tops),
                    )
                )
            # Searalize via pkl
            filepath: Path = Path(
                f"D{request.year}"
                f"-{str(request.month.value).zfill(2)}"
                f"-{str(target.day).zfill(2)}"
                f"-cloud-stats-{request.observatory.name.lower()}.pkl"
            )
            with open(filepath, "wb") as file:
                pickle.dump(tuple(result), file)
            # Persist blob
            self.instrument_access.add_blob(
                name=request.observatory.name.lower(),
                path=filepath,
                directory=f"vertical_extent/{request.year}/",
            )
            # Remove the file
            os.remove(filepath)

    @staticmethod
    def _identify_layers_and_phases(series: pd.Series):
        # So, when you come into here, you want to make it easy for yourself
        # to summarize the layers as well as the phases
        # You may need to use this two times.
        below = np.nan
        in_layer = False
        results = []  # Results starts out as just an empty list
        for pointer, index in enumerate(series.index[:-1]):
            # Note, when you are making the phases you want to keep track of the layers
            # You may need to update this...
            center = series[index]
            above = series.iloc[pointer + 1]
            if np.isnan(below) and not np.isnan(center):
                base = index - 45
                layers = []  # As soon as we come in, we create a new layer list
                in_layer = True
                current_phase = center
                current_base = base
            if in_layer:
                if current_phase != center:
                    # Then we have a new phase
                    # When we have a new phase we need to
                    # Close off the previous one and start a new one
                    current_top = index + 45
                    layers.append(
                        {
                            "base": current_base,
                            "top": current_top,
                            "depth": current_top - current_base,
                            "phase": current_phase,
                        }
                    )
                    current_base = current_top
                    current_phase = center
            if np.isnan(above) and not np.isnan(center):
                current_top = index + 45
                # phases = set(phases)
                in_layer = False
                # Add the layer information
                layers.append(
                    {
                        "base": current_base,
                        "top": current_top,
                        "depth": current_top - current_base,
                        "phase": current_phase,
                    }
                )
                # Now that you have closed this layer, you want to append layers to results
                results.append(layers)
            # Update the below before moving on
            below = center
        # Now that you've gone through all except the last one, handle the edge
        # TODO: You need to mess with the last one as well.
        # index = series.index[-1]  # Use the last index
        # center = series[index]  # Center on the top
        # if not np.isnan(center):
        #     top = index + 45
        #     if np.isnan(below):
        #         base = index - 45
        #         phases = []
        #     phases.append(int(center))
        #     # Add the layer information
        #     results.append(
        #         {"base": base, "top": top, "depth": top - base, "phases": set(phases)}
        #     )
        return results

    # def make_fig_3_bases(self, request: ObservatoryRequest) -> None:
    #     """Extract fractioin of the time that lidar detected the base."""
    #     # Get a list of all the relevant blobs
    #     blobs: tuple[str, ...] = self.instrument_access.list_blobs(
    #         container=request.observatory.name.lower(),
    #         name_starts_with=f"vertical_extent/{request.year}/",
    #     )
    #     # Extract the data for each day
    #     total: int = 0
    #     lidar: int = 0
    #     radar: int = 0
    #     both: int = 0
    #     for target in self._dates_in_month(request.year, request.month.value):
    #         print(target)
    #         selected: tuple[str, ...] = self.filter_context.apply(
    #             target, blobs, strategy=NamesByDate(), time=False
    #         )
    #         if not selected:
    #             continue
    #         # Read the pickle file
    #         layers: tuple[VerticalLayers, ...] = self._read_pickle(selected[0], request)
    #         if not layers:
    #             continue
    #         for time_slice in layers:
    #             total += 1
    #             try:
    #                 match time_slice.bases[0].code.top:
    #                     case 1:
    #                         lidar += 1
    #                     case 2:
    #                         radar += 1
    #                     case 3:
    #                         both += 1
    #             except IndexError:
    #                 continue
    #         # Now that you have gone through all of the times,
    #         # You need to save the total, lidar, radar, and both
    #         # Then you can start to make the plot
    #     return {"total": total, "both": both, "lidar": lidar, "radar": radar}
    #     # # Searalize via pkl
    #     # filepath: Path = Path(
    #     #     f"D{request.year}"
    #     #     f"-{str(request.month.value).zfill(2)}"
    #     #     f"-{str(target.day).zfill(2)}"
    #     #     f"-cloud-stats-{request.observatory.name.lower()}.pkl"
    #     # )
    #     # with open(filepath, "wb") as file:
    #     #     pickle.dump(tuple(result), file)
    #     # # Persist blob
    #     # self.instrument_access.add_blob(
    #     #     name=request.observatory.name.lower(),
    #     #     path=filepath,
    #     #     directory=f"vertical_extent/{request.year}/",
    #     # )
    #     # # Remove the file
    #     # os.remove(filepath)

    # def make_fig_3_tops(self, request: ObservatoryRequest) -> None:
    #     """Extract fractioin of the time that lidar detected the base."""
    #     # Get a list of all the relevant blobs
    #     blobs: tuple[str, ...] = self.instrument_access.list_blobs(
    #         container=request.observatory.name.lower(),
    #         name_starts_with=f"vertical_extent/{request.year}/",
    #     )
    #     # Extract the data for each day
    #     total: int = 0
    #     lidar: int = 0
    #     radar: int = 0
    #     both: int = 0
    #     for target in self._dates_in_month(request.year, request.month.value):
    #         print(target)
    #         selected: tuple[str, ...] = self.filter_context.apply(
    #             target, blobs, strategy=NamesByDate(), time=False
    #         )
    #         if not selected:
    #             continue
    #         # Read the pickle file
    #         layers: tuple[VerticalLayers, ...] = self._read_pickle(selected[0], request)
    #         if not layers:
    #             continue
    #         for time_slice in layers:
    #             total += 1
    #             try:
    #                 match time_slice.tops[0].code.bottom:
    #                     case 1:
    #                         lidar += 1
    #                     case 2:
    #                         radar += 1
    #                     case 3:
    #                         both += 1
    #             except IndexError:
    #                 continue
    #         # Now that you have gone through all of the times,
    #         # You need to save the total, lidar, radar, and both
    #         # Then you can start to make the plot
    #     return {"total": total, "both": both, "lidar": lidar, "radar": radar}

    # def make_fig_4_layers(self, request: ObservatoryRequest) -> None:
    #     """Extract fractioin of the time that lidar detected the base."""
    #     # Get a list of all the relevant blobs
    #     blobs: tuple[str, ...] = self.instrument_access.list_blobs(
    #         container=request.observatory.name.lower(),
    #         name_starts_with=f"vertical_extent/{request.year}/",
    #     )
    #     # Extract the data for each day
    #     zero = 0
    #     one = 0
    #     two = 0
    #     three = 0
    #     four = 0
    #     five = 0
    #     for target in self._dates_in_month(request.year, request.month.value):
    #         print(target)
    #         selected: tuple[str, ...] = self.filter_context.apply(
    #             target, blobs, strategy=NamesByDate(), time=False
    #         )
    #         if not selected:
    #             continue
    #         # Read the pickle file
    #         layers: tuple[VerticalLayers, ...] = self._read_pickle(selected[0], request)
    #         if not layers:
    #             continue
    #         for time_slice in layers:
    #             layers = len(time_slice.bases)
    #             match layers:
    #                 case 0:
    #                     zero += 1
    #                 case 1:
    #                     one += 1
    #                 case 2:
    #                     two += 1
    #                 case 3:
    #                     three += 1
    #                 case 4:
    #                     four += 1
    #                 case 5:
    #                     five += 1
    #                 case _:
    #                     five += 1
    #         # Now that you have gone through all of the times,
    #         # You need to save the total, lidar, radar, and both
    #         # Then you can start to make the plot
    #     return {
    #         "zero": zero,
    #         "one": one,
    #         "two": two,
    #         "three": three,
    #         "four": four,
    #         "five": five,
    #     }

    def create_daily_layer_plots(self, request: DailyRequest) -> None:
        """Create daily files for a given instrument, observatory, month and year."""
        # Get a list of all the relevant blobs
        blobs: tuple[str, ...] = self.instrument_access.list_blobs(
            container=request.observatory.name.lower(),
            name_starts_with=f"{request.instrument.name.lower()}/daily_30smplcmask1zwang/{request.year}/",
        )
        # Create a daily file for each day in the month
        monthly_datetimes: list[datetime] = []
        monthly_layers: list[list[np.nan | int]] = []
        for target in self._dates_in_month(request.year, request.month.value):
            print(target)
            selected: tuple[str, ...] = self.filter_context.apply(
                target,
                blobs,
                strategy=NamesByDate(),
                time=False,
            )
            if not selected:
                continue
            # Select the Strategy
            match (request.observatory, request.instrument):
                case (Observatory.UTQIAGVIK, Instrument.KAZR):
                    strategy: TransformationStrategy = UtqiagvikKazrDaily()
            # Generate a InstrumentData for each DataSet corresponding to the target date
            results: tuple[InstrumentData, ...] = tuple(
                self._generate_data(
                    selected,
                    request,
                    strategy=strategy,
                )
            )
            if not results:
                continue
            # Filter so only the target date exists in a single instance of `InstrumentData`
            # There should only be one Instrument data
            data: InstrumentData = results[0]
            if not data:
                continue
            # You are just going to do this for every time
            times: list[int] = list(data.variables["offset"].values)
            elevations: list[int] = list(data.variables["range"].values)
            default_values: list[list[int]] = [
                [np.nan for _ in elevations] for _ in times
            ]
            layers: pd.DataFrame = pd.DataFrame(
                default_values, index=times, columns=elevations
            )
            for i, time in enumerate(layers.index):
                monthly_datetimes.append(
                    datetime(target.year, target.month, target.day)
                    + timedelta(seconds=time)
                )
                base_elevations = data.variables["cloud_layer_base_height"].values[i]
                top_elevations = data.variables["cloud_layer_top_height"].values[i]
                if not any(base_elevations) and not any(top_elevations):
                    monthly_layers.append(layers.iloc[i, :])
                    continue
                layer = 1
                for base, top in zip(base_elevations, top_elevations):
                    if not base and not top:
                        break
                    layers.iloc[
                        i, (base <= layers.columns) & (layers.columns <= top)
                    ] = layer
                    layer += 1
                # Now that you are done with the layers
                monthly_layers.append(layers.iloc[i, :])
        monthly_df: pd.DataFrame = pd.DataFrame(
            monthly_layers, index=monthly_datetimes, columns=list(layers.columns)
        )
        # Plot the results
        plt.matshow(
            monthly_df.T,
            aspect="auto",
            origin="lower",
            extent=[
                monthly_df.index.min(),
                monthly_df.index.max(),
                monthly_df.columns.min() / 1000,
                monthly_df.columns.max() / 1000,
            ],
        )
        plt.colorbar()
        plt.gca().xaxis.tick_bottom()
        plt.xlabel("Timestamp, [UTC]")
        plt.ylabel("Range, [km]")
        plt.title(
            f"Cloud Layers, {request.observatory.name.capitalize()} ({request.month.name.capitalize()}. {request.year})"
        )
        plt.savefig(
            f"{request.month.name.capitalize()}-{request.year}.png", bbox_inches="tight"
        )
        # Searalize via pkl
        filepath: Path = Path(
            f"D{request.year}"
            f"-{str(request.month.value).zfill(2)}"
            f"-{str(target.day).zfill(2)}"
            f"-cloud-layers-numbered-{request.observatory.name.lower()}.pkl"
        )
        monthly_df.to_pickle(filepath)

    @staticmethod
    def _dates_in_month(year: int, month: int) -> Generator[date, None, None]:
        current = datetime(year, month, 1)
        while current.month == month:
            yield date(year, month, current.day)
            current = current + timedelta(days=1)

    def _generate_data(
        self,
        selected: tuple[str, ...],
        request: DailyRequest,
        strategy: TransformationStrategy,
    ) -> Generator[InstrumentData, None, None]:
        self.transformation_context.strategy = strategy
        for name in selected:
            filename = self.instrument_access.download_blob(
                container=request.observatory.name.lower(),
                name=name,
            )
            filepath: Path = Path.cwd() / filename
            with DataSet(filename) as dataset:
                yield self.transformation_context.hydrate(dataset, filepath)
            os.remove(filepath)

    @staticmethod
    def _resample(df: pd.DataFrame, base: int, transpose: bool, method: str):
        if transpose:
            df = df.T
        df["new_column"] = [base * round(i / base) for i in df.index]
        match method:
            case "mode":
                df = df.groupby("new_column").agg(lambda x: min(pd.Series.mode(x)))
            case "mean":
                df = df.groupby("new_column").mean()
            case _:
                raise ValueError("invalid method")
        if transpose:
            df = df.T
        return df

    @staticmethod
    def _reindex(df: pd.DataFrame, method: str):
        match method:
            case "time":
                df = df.reindex(
                    [i for i in range(0, 60 * 60 * 24 + 1, 60)], method="ffill"
                )
            case "height":
                df = df.T
                df = df.reindex([i for i in range(0, 17501, 90)], method="ffill")
                df = df.T
            case _:
                raise ValueError("invalid method: try 'time' or 'height'")
        return df

    def _reformat(self, df: pd.DataFrame, method: str):
        print("resample time")
        df = self._resample(df, 60, transpose=False, method=method)
        print("resample height")
        df = self._resample(df, 90, transpose=True, method=method)

        print("reindex time")
        df = self._reindex(df, "time")
        print("reindex height")
        df = self._reindex(df, "height")
        return df

    def _reformat_1D(self, df: pd.DataFrame, method: str):
        print("resample time")
        df = self._resample(df, 60, transpose=False, method=method)

        print("reindex time")
        df = self._reindex(df, "time")

        return df

    # def _read_pickle(
    #     self, name: str, request: ObservatoryRequest
    # ) -> tuple[VerticalLayers, ...]:
    #     filename = self.instrument_access.download_blob(
    #         container=request.observatory.name.lower(),
    #         name=name,
    #     )
    #     filepath: Path = Path.cwd() / filename
    #     with open(filepath, "rb") as file:
    #         result = pickle.load(file)
    #     os.remove(filepath)
    #     return result

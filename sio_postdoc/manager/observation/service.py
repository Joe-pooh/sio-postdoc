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

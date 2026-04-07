addpath(genpath(pwd));

%% Data loading
raw = readtable('wind_data\wind condition @Akida.xlsx');

%% Assign WD/WS for wind rose analysis
windDire  = raw.windDire;
windSpeed = raw.windSpd;

%% Remove NaN data from lidar records
inan            = isnan(windDire .* windSpeed);
windDire(inan)  = [];
windSpeed(inan) = [];

RTick = [0 0.05 0.10 0.15 0.20 0.25 0.30];
RTickLabel = {'0','5','10','15', '20', '25', '30'};

WindDireLabel = {'N', 'NNE','NE','ENE','E','ESE', 'SE','SSE', ...
                 'S','SSW', 'SW','WSW', 'W','WNW', 'NW','NNW'};

%% Mean wind speed for each wind direction
for i = 1:16

    wd           = (i-1) * 22.5;
    i_wd         = windDire == wd;

    windDire_wd  = windDire(i_wd);

    occurance(i) = sum(i_wd) / length(windDire);

    windSpeed_wd = windSpeed(i_wd);
    windSpeed_wd = windSpeed_wd(windSpeed_wd > 3);
    ws_mean(i)   = mean(windSpeed_wd);

end

figure;
polarplot(deg2rad(0:22.5:360 + 22.5), [occurance occurance(1:2)], ...
    'r-','LineWidth',2.5,'displayname','Veer');

ax = gca;
ax.ThetaDir          = 'clockwise';
ax.ThetaZeroLocation = 'top';
ax.ThetaTick         = 0:22.5:360;
ax.ThetaTickLabel    = {'N', 'NNE','NE','ENE','E','ESE', 'SE','SSE', ...
                        'S','SSW', 'SW','WSW', 'W','WNW', 'NW','NNW'}';

ax.FontName = 'Time';
set(gca,'Fontname', 'Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 8 5]*1.5);  % Figure size

figure;
bar(WindDireLabel, occurance, ...
    'FaceColor',[113, 180, 255]/256, ...
    'EdgeColor',[113, 180, 255]/256, ...
    'LineWidth',0.1);
ylabel('Probability');

set(gca,'Fontname', 'Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 10 5]);  % Figure size

figure;
bar(WindDireLabel, ws_mean, ...
    'FaceColor',[113, 180, 255]/256, ...
    'EdgeColor',[113, 180, 255]/256, ...
    'LineWidth',0.1);
ylabel('Avg. Wind Speed (m/s)');

yline(3,'k--');
ylim([0 8])

set(gca,'Fontname', 'Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 10 5]);  % Figure size

figure;
histogram(windSpeed, ...
    'BinWidth',1, ...
    'FaceColor',[113, 180, 255]/256, ...
    'EdgeColor',[113, 180, 255]/256, ...
    'Normalization','pdf');

xlabel('Wind Speed (m/s)');
ylabel('Probability');
xlim([0 15]);
ylim([0 0.4]);

set(gca,'Fontname', 'Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 10 6]);  % Figure size

%% === 1. Plot the original wind speed histogram ===
figure;
histogram(windSpeed, ...
    'BinWidth',0.5, ...
    'Normalization','pdf', ...
    'FaceColor',[113,180,255]/256, ...
    'EdgeColor',[113,180,255]/256);
hold on

%% === 2. Two-parameter Weibull fitting (MLE) ===
% wblfit returns [A_hat, k_hat]
[paramHat, paramCI] = wblfit(windSpeed);
A_hat = paramHat(1);    % Scale parameter A
k_hat = paramHat(2);    % Shape parameter k

%% === 3. Generate the fitted curve ===
x_plot = linspace(0,15,200);
y_plot = wblpdf(x_plot, A_hat, k_hat);

%% === 4. Overlay the fitted curve ===
hFit = plot(x_plot, y_plot, 'r-', 'LineWidth',2);
legendText = sprintf('Weibull fit (A=%.2f, k=%.2f)', A_hat, k_hat);

%% === 5. Optionally mark the sample mean ===
xline(mean(windSpeed), '--k', 'Mean', 'LabelOrientation','horizontal');

%% === 6. Axis and legend settings ===
xlabel('Wind Speed (m/s)');
ylabel('Probability Density');
xlim([0 15]);
ylim([0 0.4]);
legend(hFit, legendText, 'Location','northeast');

%% === 7. Font and figure size settings ===
set(gca, 'FontName','Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 10 6]);

%% Wind speed distribution for each wind direction
figure;
for i = 1:16

    wd           = (i-1) * 22.5;
    i_wd         = windDire == wd;

    windDire_wd  = windDire(i_wd);

    occurance(i) = sum(i_wd) / length(windDire);

    windSpeed_wd = windSpeed(i_wd);
    windSpeed_wd = windSpeed_wd(windSpeed_wd > 3);

    subplot(4,4,i);
    histogram(windSpeed_wd, ...
        'BinEdges',[3 7 11 15], ...
        'Normalization','probability', ...
        'FaceColor',[113, 180, 255]/256, ...
        'EdgeColor',[113, 180, 255]/256);

    xlabel('Wind Speed (m/s)');
    ylabel('Probability');
    xlim([0 20]);
    ylim([0 1])

    title(WindDireLabel{i});
    set(gca,'Fontname', 'Times New Roman','FontSize',10);

end

set(gcf, 'Units','centimeters', 'Position',[1 1 25 20]);  % Figure size

figure;

dTheta = 22.5;

polarWindRose = polaraxes;
polarWindRose.ThetaDir = 'clockwise';
polarWindRose.ThetaZeroLocation = 'top';

polarWindRose.ThetaTick = 0:22.5:360;
polarWindRose.ThetaTickLabel = {'N', 'NNE','NE','ENE','E','ESE', 'SE','SSE', ...
                                'S','SSW', 'SW','WSW', 'W','WNW', 'NW','NNW'}';
polarWindRose.FontName = 'Times';

cla(polarWindRose);
hold(polarWindRose,'on');

polarhistogram(polarWindRose, deg2rad(windDire(windSpeed<15)), deg2rad(0:dTheta:360), ...
    'Normalization','probability', 'FaceColor','#f3ed27', 'displayname','11 - 15 m/s');

% polarhistogram(polarWindRose,deg2rad(windDire(windSpeed<12)),deg2rad(0:dTheta:360),...
%     'Normalization','probability', 'FaceColor','#fcaa33','displayname','15 - 20 m/s');

polarhistogram(polarWindRose, deg2rad(windDire(windSpeed<11)), deg2rad(0:dTheta:360), ...
    'Normalization','probability', 'FaceColor','#e97256', 'displayname','7 - 11 m/s');

% polarhistogram(polarWindRose,deg2rad(windDire(windSpeed<7)),deg2rad(0:dTheta:360),...
%     'Normalization','probability', 'FaceColor','#c5407e','displayname','5 - 10 m/s');

polarhistogram(polarWindRose, deg2rad(windDire(windSpeed<7 & windSpeed>3)), deg2rad(0:dTheta:360), ...
    'Normalization','probability', 'FaceColor','#8005a8', 'displayname','3 - 7 m/s');

legend(polarWindRose,'Show','Location','eastoutside');

figure;

dTheta = 22.5;               % Width of each directional sector
half   = dTheta / 2;         % Half-sector width

% First compute the shifted edge vector
edges = -half : dTheta : 360-half;

polarWindRose = polaraxes;
polarWindRose.ThetaDir          = 'clockwise';
polarWindRose.ThetaZeroLocation = 'top';
polarWindRose.ThetaTick         = 0:dTheta:360;
polarWindRose.ThetaTickLabel    = {'N','NNE','NE','ENE','E','ESE','SE','SSE', ...
                                   'S','SSW','SW','WSW','W','WNW','NW','NNW'}';
polarWindRose.FontName          = 'Times';

cla(polarWindRose);
hold(polarWindRose,'on');

% Specify BinEdges instead of centers or width directly
polarhistogram(polarWindRose, deg2rad(windDire(windSpeed<15)), ...
               'BinEdges', deg2rad(edges), ...
               'Normalization','probability', ...
               'FaceColor', '#f3ed27', ...
               'DisplayName','11 - 15 m/s');

polarhistogram(polarWindRose, deg2rad(windDire(windSpeed<11)), ...
               'BinEdges', deg2rad(edges), ...
               'Normalization','probability', ...
               'FaceColor', '#e97256', ...
               'DisplayName','7 - 11 m/s');

polarhistogram(polarWindRose, deg2rad(windDire(windSpeed<7 & windSpeed>3)), ...
               'BinEdges', deg2rad(edges), ...
               'Normalization','probability', ...
               'FaceColor', '#8005a8', ...
               'DisplayName','3 - 7 m/s');

legend(polarWindRose,'Show','Location','eastoutside');

%% === 1. Plot the original wind speed histogram ===
figure;
histogram(windSpeed, ...
    'BinWidth',1, ...
    'Normalization','pdf', ...
    'FaceColor',[113,180,255]/256, ...
    'EdgeColor',[113,180,255]/256);
hold on

%% === 2. Two-parameter Weibull fitting (MLE) ===
% wblfit returns [A_hat, k_hat]
[paramHat, paramCI] = wblfit(windSpeed);
A_hat = paramHat(1);    % Scale parameter A
k_hat = paramHat(2);    % Shape parameter k

%% === 3. Generate the fitted curve ===
x_plot = linspace(0,15,200);
y_plot = wblpdf(x_plot, A_hat, k_hat);

%% === 4. Overlay the fitted curve ===
hFit = plot(x_plot, y_plot, 'r-', 'LineWidth',2);
legendText = sprintf('Weibull fit (A=%.2f, k=%.2f)', A_hat, k_hat);

%% === 5. Optionally mark the sample mean ===
xline(mean(windSpeed), '--k');

%% === 6. Axis and legend settings ===
xlabel('Wind Speed (m/s)');
ylabel('Probability Density');
xlim([0 15]);
ylim([0 0.4]);
legend(hFit, legendText, 'Location','northeast');

%% === 7. Font and figure size settings ===
set(gca, 'FontName','Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 10 6]);

%% ==== Input data ====
% wind_speed: wind speed (m/s), column vector
% wind_dir_idx: wind direction index (1~16), column vector
% Assume both vectors have the same length
% load('your_data.mat'); % If using a MAT file

wind_speed   = windSpeed;
wind_dir_deg = windDire;

%% ==== Input data ====
% wind_speed: wind speed (m/s)
% wind_dir_deg: wind direction (deg), range 0~360
% load('your_data.mat'); % If using a MAT file

%% ==== Settings ====
speed_bin_width = 2;  % Wind speed bin width
speed_edges = 0:speed_bin_width:ceil(max(wind_speed));  % Wind speed bin edges

% Wind direction bins (centers at 0:22.5:360-22.5, each bin width = 22.5 deg)
dir_bin_width = 22.5;
dir_edges = -dir_bin_width/2 : dir_bin_width : 360 - dir_bin_width/2;
dir_edges(end+1) = dir_edges(end) + dir_bin_width;  % Closed interval

% Map wind direction to 0~360 to avoid negative angles
wind_dir_deg = mod(wind_dir_deg, 360);

%% ==== Compute JPD ====
[counts,~,~] = histcounts2(wind_speed, wind_dir_deg, speed_edges, dir_edges);

% Convert to probability (normalized to 1)
counts_prob = counts / sum(counts(:));

%% ==== Plot ====
figure;
imagesc((0:22.5:360-22.5)-12.25, speed_edges(1:end-1) + speed_bin_width/2, counts_prob);
set(gca, 'YDir', 'normal');  % Display Y-axis in normal direction

colormap(customcolormap_bank('MyColor1'));
% caxis([2 12]);

% Set wind direction labels
wind_labels = {'N','NNE','NE','ENE','E','ESE','SE','SSE', ...
               'S','SSW','SW','WSW','W','WNW','NW','NNW'};
set(gca, 'XTick', 0:22.5:360-22.5, 'XTickLabel', wind_labels);

xlabel('Wind Direction');
ylabel('Wind Speed (m/s)');
title('Joint Probability Density (Wind Speed & Direction)');
colorbar;

set(gca, 'FontName','Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 16 8]*0.8);

%% ==== If percentage output is needed ====
% counts_prob_percent = counts_prob * 100;

%% ==== Input ====
% wind_speed   : wind speed (m/s), vector
% wind_dir_deg : wind direction (deg), vector, arbitrary range
%                (will be mapped into 0~360)
% Both must have the same length

%% ==== Settings ====
% 1) Three wind speed ranges
speed_edges = [3 7 11 15];               % [3,7), [7,11), [11,15]
speed_centers = (speed_edges(1:end-1) + speed_edges(2:end))/2;
speed_labels  = {'3–7','7–11','11–15'};

% 2) Sixteen wind direction sectors
% Centers: 0:22.5:337.5, each sector width = 22.5 deg
dir_bin_width = 22.5;
dir_edges = -dir_bin_width/2 : dir_bin_width : 360 - dir_bin_width/2;
dir_edges(end+1) = dir_edges(end) + dir_bin_width;   % Closed interval
dir_centers = 0:22.5:360-22.5;
dir_labels = {'N','NNE','NE','ENE','E','ESE','SE','SSE', ...
              'S','SSW','SW','WSW','W','WNW','NW','NNW'};

% Map wind direction to 0~360
wind_dir_deg = mod(wind_dir_deg, 360);

%% ==== Compute JPD (only for data within the three speed ranges) ====
[counts,~,~] = histcounts2(wind_speed, wind_dir_deg, speed_edges, dir_edges);

% Normalize to probability
% Only samples within the selected speed range [3,15] are considered
total_in_bins = sum(counts(:));
if total_in_bins == 0
    warning('No data are found within the selected wind speed range [3,15] m/s.');
    probs = counts;  % All zeros
else
    probs = counts / total_in_bins;
end

%% ==== Plot ====
figure;
imagesc(dir_centers-12.25, speed_centers, probs);
set(gca, 'YDir', 'normal');
set(gca, 'XTick', dir_centers, 'XTickLabel', dir_labels);
set(gca, 'YTick', speed_centers, 'YTickLabel', speed_labels);

xlabel('Wind Direction');
ylabel('Wind Speed Bin (m/s)');
title('Joint Probability Density');
colorbar;

colormap(customcolormap_bank('MyColor1'));
% caxis([2 12]);

set(gca, 'FontName','Times New Roman','FontSize',10);
set(gcf, 'Units','centimeters', 'Position',[1 1 16 12]*0.6);

%% ==== Optional: export probability table in percentage ====
% Rows = wind speed bins, Columns = wind direction sectors
% prob_percent = 100 * probs;
% T = array2table(prob_percent, 'RowNames', speed_labels, ...
%     'VariableNames', strrep(dir_labels,'-','_'));